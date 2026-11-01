export function isImportCredentialError(message: string | null | undefined): boolean {
  if (!message) return false
  return /(rejected credentials|telephony credentials rejected|auth failed|credentials could not be verified)/i.test(
    message,
  )
}
