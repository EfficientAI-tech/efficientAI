import { Globe } from 'lucide-react'
import type { ToolConnectionType } from '../../types/api'

/** Brand marks in /public/tool-logos (Simple Icons, CC0; Slack from its brand geometry). */
const LOGOS: Record<string, { src: string; alt: string }> = {
  slack: { src: '/tool-logos/slack.svg', alt: 'Slack' },
  notion: { src: '/tool-logos/notion.svg', alt: 'Notion' },
  gdrive: { src: '/tool-logos/googledrive.svg', alt: 'Google Drive' },
  postgres: { src: '/tool-logos/postgresql.svg', alt: 'PostgreSQL' },
  mcp: { src: '/tool-logos/modelcontextprotocol.svg', alt: 'Model Context Protocol' },
}

/** Logo for a preset id, falling back to the connection type (HTTP APIs get a globe). */
function toolLogoKey(preset?: string | null, connectionType?: ToolConnectionType | string): string {
  if (preset && LOGOS[preset]) return preset
  if (connectionType === 'postgres') return 'postgres'
  if (connectionType === 'mcp') return 'mcp'
  return 'http'
}

export default function ToolConnectionLogo({
  preset,
  connectionType,
  size = 20,
}: {
  preset?: string | null
  connectionType?: ToolConnectionType | string
  size?: number
}) {
  const logo = LOGOS[toolLogoKey(preset, connectionType)]
  if (!logo) {
    return <Globe className="shrink-0 text-gray-500" style={{ width: size, height: size }} aria-label="HTTP API" />
  }
  return <img src={logo.src} alt={logo.alt} width={size} height={size} className="shrink-0 object-contain" />
}
