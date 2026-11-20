/** Concatenate paginated API list responses until `total` items are loaded. */
export async function fetchAllPaginated<T>(
  pageSize: number,
  fetchPage: (skip: number, limit: number) => Promise<{ items: T[]; total: number }>,
): Promise<{ items: T[]; total: number }> {
  const first = await fetchPage(0, pageSize)
  if (first.items.length >= first.total) {
    return first
  }

  const items = [...first.items]
  let skip = first.items.length
  while (skip < first.total) {
    const page = await fetchPage(skip, pageSize)
    if (page.items.length === 0) {
      break
    }
    items.push(...page.items)
    skip += page.items.length
  }

  return { items, total: first.total }
}