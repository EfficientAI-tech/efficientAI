"""Core evaluation service for processing audio evaluations."""

import whisper
import time
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.database import Evaluation, EvaluationResult, EvaluationStatus, AudioFile
from app.services.metrics_service import metrics_service
from app.services.audio_service import AudioService
from app.core.exceptions import EvaluationNotFoundError, AudioFileNotFoundError

audio_service = AudioService()


class EvaluationService:
    """Service for managing evaluations."""

    def __init__(self):
        """Initialize evaluation service."""
        self.model_cache: Dict[str, Any] = {}

    def _load_model(self, model_name: Optional[str] = None) -> Any:
        """
        Load Whisper model (with caching).

        Args:
            model_name: Name of the model to load (default: "base")

        Returns:
            Loaded Whisper model
        """
        model_name = model_name or "base"

        if model_name not in self.model_cache:
            try:
                model = whisper.load_model(model_name)
                self.model_cache[model_name] = model
            except Exception as e:
                raise RuntimeError(f"Failed to load model {model_name}: {str(e)}")

        return self.model_cache[model_name]

    def process_evaluation(
        self,
        evaluation_id: UUID,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Process an evaluation job.

        Args:
            evaluation_id: Evaluation ID
            db: Database session

        Returns:
            Dictionary with evaluation results

        Raises:
            EvaluationNotFoundError: If evaluation not found
            AudioFileNotFoundError: If audio file not found
        """
        # Get evaluation
        evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
        if not evaluation:
            raise EvaluationNotFoundError(f"Evaluation {evaluation_id} not found")

        # Get audio file
        audio_file = db.query(AudioFile).filter(AudioFile.id == evaluation.audio_id).first()
        if not audio_file:
            raise AudioFileNotFoundError(f"Audio file {evaluation.audio_id} not found")

        # Update status to processing
        evaluation.status = EvaluationStatus.PROCESSING
        evaluation.started_at = datetime.utcnow()
        db.commit()

        try:
            # Load model
            model = self._load_model(evaluation.model_name)

            # Process audio
            start_time = time.time()
            result = model.transcribe(audio_file.file_path)
            end_time = time.time()

            processing_time = end_time - start_time
            transcript = result.get("text", "")

            # Calculate metrics
            metrics_requested = evaluation.metrics_requested or []
            metrics = metrics_service.calculate_metrics(
                metrics_requested=metrics_requested,
                reference_text=evaluation.reference_text,
                hypothesis_text=transcript,
                audio_duration=audio_file.duration,
                processing_time=processing_time,
            )

            # Create result record
            evaluation_result = EvaluationResult(
                evaluation_id=evaluation.id,
                transcript=transcript,
                metrics=metrics,
                raw_output=result,
                processing_time=processing_time,
                model_used=evaluation.model_name or "base",
            )
            db.add(evaluation_result)

            # Update evaluation status
            evaluation.status = EvaluationStatus.COMPLETED
            evaluation.completed_at = datetime.utcnow()
            db.commit()

            return {
                "evaluation_id": str(evaluation.id),
                "status": "completed",
                "transcript": transcript,
                "metrics": metrics,
                "processing_time": processing_time,
                "model_used": evaluation_result.model_used,
            }

        except Exception as e:
            # Update status to failed
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error_message = str(e)
            evaluation.completed_at = datetime.utcnow()
            db.commit()

            raise

    def get_evaluation_result(self, evaluation_id: UUID, db: Session) -> Optional[EvaluationResult]:
        """
        Get evaluation result.

        Args:
            evaluation_id: Evaluation ID
            db: Database session

        Returns:
            EvaluationResult if found, None otherwise
        """
        return db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == evaluation_id).first()

    def cancel_evaluation(self, evaluation_id: UUID, db: Session) -> bool:
        """
        Cancel a pending evaluation.

        Args:
            evaluation_id: Evaluation ID
            db: Database session

        Returns:
            True if cancelled, False if already processing/completed
        """
        evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
        if not evaluation:
            return False

        if evaluation.status == EvaluationStatus.PENDING:
            evaluation.status = EvaluationStatus.CANCELLED
            db.commit()
            return True

        return False


# Singleton instance
evaluation_service = EvaluationService()

