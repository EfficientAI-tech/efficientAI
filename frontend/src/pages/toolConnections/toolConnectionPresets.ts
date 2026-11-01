import type { ToolConnectionType, ToolSimulationMode } from '../../types/api'

export type McpTransport = 'streamable_http' | 'sse' | 'stdio'

export interface ToolConnectionPreset {
  id: string
  label: string
  description: string
  connectionType: ToolConnectionType
  defaultName: string
  transport?: McpTransport
  url?: string
  command?: string
  args?: string[]
  /** Secret header / env names the user should fill in. */
  secretHeaders?: string[]
  secretEnv?: string[]
  simulationMode: ToolSimulationMode
  /** Shown under the form: setup notes for this source. */
  hint: string
}

const HTTP_TOOLS_EXAMPLE = JSON.stringify(
  [
    {
      name: 'get_order',
      description: 'Look up an order by its number',
      method: 'GET',
      path: '/orders/{order_id}',
      parameters: {
        type: 'object',
        properties: { order_id: { type: 'string', description: 'Order number' } },
        required: ['order_id'],
      },
    },
  ],
  null,
  2,
)

export const HTTP_TOOLS_PLACEHOLDER = HTTP_TOOLS_EXAMPLE

/** Starting templates; every field stays editable. */
export const TOOL_CONNECTION_PRESETS: ToolConnectionPreset[] = [
  {
    id: 'slack',
    label: 'Slack',
    description: 'Search channels and messages; posting is mocked in simulations.',
    connectionType: 'mcp',
    defaultName: 'Slack',
    transport: 'stdio',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-slack'],
    secretEnv: ['SLACK_BOT_TOKEN', 'SLACK_TEAM_ID'],
    simulationMode: 'mock_writes',
    hint: 'Runs the Slack MCP server on the worker (self-hosted installs only). On EfficientAI Cloud, switch the transport to HTTP and point it at a hosted Slack MCP server.',
  },
  {
    id: 'notion',
    label: 'Notion',
    description: 'Search and read pages and databases.',
    connectionType: 'mcp',
    defaultName: 'Notion',
    transport: 'stdio',
    command: 'npx',
    args: ['-y', '@notionhq/notion-mcp-server'],
    secretEnv: ['NOTION_TOKEN'],
    simulationMode: 'mock_writes',
    hint: 'Uses a Notion internal integration token; share the pages the agent may read with that integration. Self-hosted installs only unless you switch to a hosted MCP URL.',
  },
  {
    id: 'gdrive',
    label: 'Google Drive',
    description: 'Search and read Drive files through an MCP server you host.',
    connectionType: 'mcp',
    defaultName: 'Google Drive',
    transport: 'streamable_http',
    url: 'https://',
    secretHeaders: ['Authorization'],
    simulationMode: 'mock_writes',
    hint: 'Drive needs OAuth, so run a Google Drive MCP server with your credentials and enter its URL plus the header it expects.',
  },
  {
    id: 'postgres',
    label: 'Postgres',
    description: 'Read-only SQL: list tables, describe them, run SELECTs.',
    connectionType: 'postgres',
    defaultName: 'Postgres',
    simulationMode: 'live',
    hint: 'Every query runs in a read-only transaction with a 10s timeout and a row cap. Use a database user that can only read what the agent needs.',
  },
  {
    id: 'mcp',
    label: 'Custom MCP server',
    description: 'Any MCP server reachable over HTTP.',
    connectionType: 'mcp',
    defaultName: 'MCP server',
    transport: 'streamable_http',
    url: 'https://',
    simulationMode: 'mock_writes',
    hint: 'Tools come from the server’s tools/list. Tools annotated read-only run live; others are treated as writes and mocked unless you change it below.',
  },
  {
    id: 'http',
    label: 'HTTP API',
    description: 'Your own endpoints (orders, CRM, bookings) described as tools.',
    connectionType: 'http',
    defaultName: 'Internal API',
    secretHeaders: ['Authorization'],
    simulationMode: 'mock_writes',
    hint: 'Path placeholders like {order_id} are filled from the arguments; other arguments go in the query string (GET/DELETE) or JSON body. GET tools are reads, everything else writes unless you set side_effect.',
  },
]

export function presetById(id?: string | null): ToolConnectionPreset | undefined {
  return TOOL_CONNECTION_PRESETS.find((preset) => preset.id === id)
}

export const SIMULATION_MODE_OPTIONS: { value: ToolSimulationMode; label: string; description: string }[] = [
  {
    value: 'mock_writes',
    label: 'Mock writes',
    description: 'Read tools run for real; tools that change data return a fake success.',
  },
  { value: 'live', label: 'Live', description: 'Every call runs for real, including writes.' },
  { value: 'mock_all', label: 'Mock everything', description: 'No call leaves the platform.' },
]
