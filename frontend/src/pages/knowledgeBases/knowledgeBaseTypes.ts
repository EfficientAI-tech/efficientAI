export interface KnowledgeDocument {
  id: string
  knowledge_base_id: string
  source_type: string
  original_filename?: string | null
  content_type?: string | null
  byte_size?: number | null
  status: string
  error_text?: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeDocumentView {
  knowledge_base_id: string
  knowledge_base_name: string
  document_id: string
  view_mode: string
  original_filename?: string | null
  content_type?: string | null
  text_content?: string | null
  pages?: Array<{ page?: number | null; text: string }> | null
  page_count?: number | null
}

export interface KnowledgeBaseSummary {
  id: string
  name: string
  description?: string | null
  embedding_provider?: string
  embedding_model?: string
  embedding_credential_id?: string | null
  status: string
  document_count: number
  ready_document_count: number
  failed_document_count: number
  linked_agent_count: number
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseDetail extends Omit<KnowledgeBaseSummary, 'document_count' | 'ready_document_count' | 'failed_document_count'> {
  documents: KnowledgeDocument[]
}
