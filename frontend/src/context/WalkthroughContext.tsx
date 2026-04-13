import { DependencyList, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  WalkthroughDefinition,
  WalkthroughSectionId,
  WalkthroughSectionStateMap,
  getWalkthroughDefinition,
  getWalkthroughSectionId,
} from '../components/walkthrough/walkthroughRegistry'

const WALKTHROUGH_COLLAPSED_KEY = 'efficientai.walkthrough.collapsed'

interface WalkthroughContextValue {
  isCollapsed: boolean
  setCollapsed: (collapsed: boolean) => void
  toggleCollapsed: () => void
  activeSectionId: WalkthroughSectionId | null
  activeDefinition: WalkthroughDefinition | null
  sectionState: WalkthroughSectionStateMap
  setSectionState: <K extends keyof WalkthroughSectionStateMap>(
    sectionId: K,
    state: WalkthroughSectionStateMap[K]
  ) => void
  clearSectionState: (sectionId: keyof WalkthroughSectionStateMap) => void
}

const WalkthroughContext = createContext<WalkthroughContextValue | null>(null)

export function WalkthroughProvider({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [sectionState, setSectionStateMap] = useState<WalkthroughSectionStateMap>({})

  useEffect(() => {
    const stored = localStorage.getItem(WALKTHROUGH_COLLAPSED_KEY)
    if (stored === 'true') {
      setIsCollapsed(true)
    }
  }, [])

  const setCollapsed = useCallback((collapsed: boolean) => {
    setIsCollapsed(collapsed)
    localStorage.setItem(WALKTHROUGH_COLLAPSED_KEY, String(collapsed))
  }, [])

  const toggleCollapsed = useCallback(() => {
    setIsCollapsed((prev) => {
      const next = !prev
      localStorage.setItem(WALKTHROUGH_COLLAPSED_KEY, String(next))
      return next
    })
  }, [])

  const setSectionState = useCallback(
    <K extends keyof WalkthroughSectionStateMap>(sectionId: K, state: WalkthroughSectionStateMap[K]) => {
      setSectionStateMap((prev) => {
        if (prev[sectionId] === state) {
          return prev
        }
        return { ...prev, [sectionId]: state }
      })
    },
    []
  )

  const clearSectionState = useCallback((sectionId: keyof WalkthroughSectionStateMap) => {
    setSectionStateMap((prev) => {
      if (!(sectionId in prev)) {
        return prev
      }
      const next = { ...prev }
      delete next[sectionId]
      return next
    })
  }, [])

  const activeSectionId = useMemo(
    () => getWalkthroughSectionId(location.pathname),
    [location.pathname]
  )

  const activeDefinition = useMemo(() => {
    if (!activeSectionId) {
      return null
    }
    return getWalkthroughDefinition(activeSectionId, sectionState)
  }, [activeSectionId, sectionState])

  const value = useMemo<WalkthroughContextValue>(
    () => ({
      isCollapsed,
      setCollapsed,
      toggleCollapsed,
      activeSectionId,
      activeDefinition,
      sectionState,
      setSectionState,
      clearSectionState,
    }),
    [
      isCollapsed,
      setCollapsed,
      toggleCollapsed,
      activeSectionId,
      activeDefinition,
      sectionState,
      setSectionState,
      clearSectionState,
    ]
  )

  return <WalkthroughContext.Provider value={value}>{children}</WalkthroughContext.Provider>
}

export function useWalkthrough(): WalkthroughContextValue {
  const context = useContext(WalkthroughContext)
  if (!context) {
    throw new Error('useWalkthrough must be used within WalkthroughProvider')
  }
  return context
}

export function useWalkthroughSectionState<K extends keyof WalkthroughSectionStateMap>(
  sectionId: K,
  state: WalkthroughSectionStateMap[K],
  deps: DependencyList
) {
  const { setSectionState, clearSectionState } = useWalkthrough()

  useEffect(() => {
    setSectionState(sectionId, state)
    return () => clearSectionState(sectionId)
  }, [sectionId, setSectionState, clearSectionState, ...deps])
}
