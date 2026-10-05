import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { ItemVisual } from './itemVisuals'

/** Uploaded material icons: accepted types and size (the API checks them again). */
export const ICON_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const ICON_MAX_BYTES = 1024 * 1024

/**
 * An uploaded material icon as a blob URL. The API path needs the bearer token, so it's fetched
 * with the API client. `icon_url` is versioned (a new upload changes it), so the blob URL is
 * cached by it for the whole session and shared by every card and sheet showing it.
 */
export function useMaterialIcon(iconUrl: string | null | undefined): string | null {
  const query = useQuery({
    queryKey: ['material-icon', iconUrl],
    enabled: Boolean(iconUrl),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: 1,
    queryFn: async () => {
      const blob = (await api.get<Blob>(iconUrl as string, { responseType: 'blob' })).data
      return URL.createObjectURL(blob)
    },
  })
  return iconUrl ? (query.data ?? null) : null
}

/**
 * The picture to draw for an item: a material's uploaded icon, else its bundled picture
 * (`icon_key`, or a catalog item's picture). Null → the card draws `visual.icon`.
 */
export function useItemPicture(visual: ItemVisual | null): string | null {
  const uploaded = useMaterialIcon(visual?.iconUrl)
  return uploaded ?? visual?.picture ?? null
}
