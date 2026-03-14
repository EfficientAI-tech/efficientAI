"""Celery task: generate TTS report PDF."""

from uuid import UUID

from loguru import logger

from app.database import SessionLocal

from app.workers.config import celery_app


@celery_app.task(name="generate_tts_report_pdf", bind=True, max_retries=1)
def generate_tts_report_pdf_task(self, report_job_id: str):
    """Generate a Voice Playground PDF report and store it in S3."""
    from app.models.database import (
        TTSComparison,
        TTSSample,
        TTSReportJob,
        TTSReportJobStatus,
    )
    from app.services.storage.s3_service import s3_service
    from app.services.reporting.voice_playground_report_service import voice_playground_report_service

    db = SessionLocal()
    try:
        report_job = db.query(TTSReportJob).filter(TTSReportJob.id == UUID(report_job_id)).first()
        if not report_job:
            logger.error(f"[TTS Report] Job {report_job_id} not found")
            return {"error": "report_job_not_found"}

        comparison = (
            db.query(TTSComparison)
            .filter(
                TTSComparison.id == report_job.comparison_id,
                TTSComparison.organization_id == report_job.organization_id,
            )
            .first()
        )
        if not comparison:
            report_job.status = TTSReportJobStatus.FAILED.value
            report_job.error_message = "Comparison not found"
            db.commit()
            return {"error": "comparison_not_found"}

        report_job.status = TTSReportJobStatus.PROCESSING.value
        report_job.celery_task_id = self.request.id
        db.commit()

        samples = (
            db.query(TTSSample)
            .filter(TTSSample.comparison_id == comparison.id)
            .order_by(TTSSample.run_index, TTSSample.sample_index)
            .all()
        )

        payload = voice_playground_report_service.build_payload(comparison, samples)
        pdf_bytes = voice_playground_report_service.render_pdf(payload)

        report_filename = (
            f"voice-playground-report-{comparison.simulation_id or str(comparison.id)[:8]}.pdf"
        )
        s3_key = (
            f"{s3_service.prefix}organizations/{report_job.organization_id}/voicePlayground/"
            f"{comparison.id}/reports/{report_job.id}.pdf"
        )
        s3_service.upload_file_by_key(
            file_content=pdf_bytes,
            key=s3_key,
            content_type="application/pdf",
        )

        report_job.status = TTSReportJobStatus.COMPLETED.value
        report_job.filename = report_filename
        report_job.s3_key = s3_key
        report_job.error_message = None
        db.commit()

        return {"status": "completed", "s3_key": s3_key}
    except Exception as exc:
        logger.error(f"[TTS Report] Task failed: {exc}", exc_info=True)
        try:
            report_job = db.query(TTSReportJob).filter(TTSReportJob.id == UUID(report_job_id)).first()
            if report_job:
                report_job.status = TTSReportJobStatus.FAILED.value
                report_job.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
