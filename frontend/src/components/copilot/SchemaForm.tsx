/**
 * Minimal JSON-Schema form for editing copilot proposals before confirming.
 * Handles the shapes our Pydantic payloads produce: strings (short / long),
 * numbers, booleans, enums, string lists, lists of objects and nested objects.
 * Anything else falls back to a JSON textarea.
 */

type Schema = {
  type?: string | string[]
  enum?: unknown[]
  items?: Schema
  properties?: Record<string, Schema>
  required?: string[]
  description?: string
  maxLength?: number
  anyOf?: Schema[]
  $ref?: string
  $defs?: Record<string, Schema>
  default?: unknown
  minimum?: number
  maximum?: number
  format?: string
}

type Value = unknown

const LONG_TEXT = 200
// Ids and internal references stay read-only: changing them would point the action elsewhere.
const HIDDEN_KEYS = /(^|_)(id|ids)$|^agent$|^call_import$|^evaluation$/

function resolve(schema: Schema, root: Schema): Schema {
  let current = schema
  for (let i = 0; i < 5 && current.$ref; i++) {
    const name = current.$ref.split('/').pop() as string
    current = { ...(root.$defs?.[name] ?? {}), description: current.description ?? root.$defs?.[name]?.description }
  }
  if (current.anyOf) {
    const concrete = current.anyOf.find((s) => s.type !== 'null')
    if (concrete) return { ...resolve(concrete, root), description: current.description, default: current.default }
  }
  return current
}

function label(key: string): string {
  const text = key.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function Field({
  name,
  schema,
  root,
  value,
  onChange,
  disabled,
}: {
  name: string
  schema: Schema
  root: Schema
  value: Value
  onChange: (value: Value) => void
  disabled?: boolean
}) {
  const s = resolve(schema, root)
  const inputClass =
    'w-full rounded-md border border-gray-300 px-2 py-1 text-xs focus:border-gray-500 focus:outline-none disabled:bg-gray-50'

  if (s.enum) {
    return (
      <select className={inputClass} disabled={disabled} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
        {s.enum.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option)}
          </option>
        ))}
      </select>
    )
  }
  if (s.type === 'boolean') {
    return (
      <input type="checkbox" disabled={disabled} checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
    )
  }
  if (s.type === 'integer' || s.type === 'number') {
    return (
      <input
        type="number"
        className={inputClass}
        disabled={disabled}
        min={s.minimum}
        max={s.maximum}
        value={value === null || value === undefined ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    )
  }
  if (s.type === 'string') {
    const text = String(value ?? '')
    const long = (s.maxLength ?? 0) > LONG_TEXT || text.length > 80 || text.includes('\n')
    return long ? (
      <textarea
        className={`${inputClass} min-h-[64px]`}
        disabled={disabled}
        maxLength={s.maxLength}
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
    ) : (
      <input
        className={inputClass}
        disabled={disabled}
        maxLength={s.maxLength}
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  if (s.type === 'array' && s.items) {
    const items = Array.isArray(value) ? value : []
    const itemSchema = resolve(s.items, root)
    if (itemSchema.type === 'string') {
      return (
        <textarea
          className={`${inputClass} min-h-[48px]`}
          disabled={disabled}
          placeholder="One per line"
          value={items.join('\n')}
          onChange={(e) => onChange(e.target.value.split('\n').filter((line) => line.trim() !== ''))}
        />
      )
    }
    if (itemSchema.type === 'object' && itemSchema.properties) {
      return (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div key={index} className="rounded-md border border-gray-200 p-2">
              <div className="mb-1 flex justify-between text-[11px] text-gray-500">
                <span>#{index + 1}</span>
                {!disabled && (
                  <button type="button" className="hover:text-red-600" onClick={() => onChange(items.filter((_, i) => i !== index))}>
                    Remove
                  </button>
                )}
              </div>
              <ObjectFields
                schema={itemSchema}
                root={root}
                value={(item as Record<string, Value>) ?? {}}
                onChange={(next) => onChange(items.map((it, i) => (i === index ? next : it)))}
                disabled={disabled}
              />
            </div>
          ))}
        </div>
      )
    }
  }
  if (s.type === 'object' && s.properties) {
    return (
      <ObjectFields
        schema={s}
        root={root}
        value={(value as Record<string, Value>) ?? {}}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }
  return (
    <textarea
      className={`${inputClass} font-mono`}
      disabled={disabled}
      defaultValue={JSON.stringify(value ?? null, null, 2)}
      onBlur={(e) => {
        try {
          onChange(JSON.parse(e.target.value))
        } catch {
          // Keep the previous value until the JSON is valid.
        }
      }}
      aria-label={name}
    />
  )
}

function ObjectFields({
  schema,
  root,
  value,
  onChange,
  disabled,
}: {
  schema: Schema
  root: Schema
  value: Record<string, Value>
  onChange: (value: Record<string, Value>) => void
  disabled?: boolean
}) {
  const properties = Object.entries(schema.properties ?? {}).filter(([key]) => !HIDDEN_KEYS.test(key))
  return (
    <div className="space-y-2">
      {properties.map(([key, prop]) => (
        <label key={key} className="block">
          <span className="mb-0.5 block text-[11px] font-medium text-gray-600">{label(key)}</span>
          <Field
            name={key}
            schema={prop}
            root={root}
            value={value[key]}
            disabled={disabled}
            onChange={(next) => onChange({ ...value, [key]: next })}
          />
        </label>
      ))}
    </div>
  )
}

export function SchemaForm({
  schema,
  value,
  onChange,
  disabled,
}: {
  schema: Schema
  value: Record<string, Value>
  onChange: (value: Record<string, Value>) => void
  disabled?: boolean
}) {
  return <ObjectFields schema={schema} root={schema} value={value} onChange={onChange} disabled={disabled} />
}

export type { Schema as JsonSchema }
