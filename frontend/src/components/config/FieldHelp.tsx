/**
 * FieldHelp — inline format hint shown below any configuration input.
 *
 * Usage:
 *   <FieldHelp example="192.168.1.10" hint="IPv4 address of the device" />
 */
export default function FieldHelp({
  example,
  hint,
}: {
  example: string
  hint?: string
}) {
  return (
    <div className="mt-1.5 flex items-start gap-1.5">
      <span className="text-gray-600 text-xs mt-0.5">ⓘ</span>
      <div className="text-xs text-gray-500 space-x-1">
        <span>Format:</span>
        <span className="font-mono text-gray-400 bg-gray-800 px-1 py-0.5 rounded">{example}</span>
        {hint && <span className="text-gray-600">· {hint}</span>}
      </div>
    </div>
  )
}
