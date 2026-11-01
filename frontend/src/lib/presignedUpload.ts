export async function uploadFileToPresignedPutUrl(
  uploadUrl: string,
  file: File,
  contentType: string,
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': contentType },
  })
  if (!response.ok) {
    throw new Error(`Direct storage upload failed (${response.status}).`)
  }
}
