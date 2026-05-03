import { create } from 'zustand'

type SettingsState = {
  settings: any
  setSettings: (s: any) => void
}

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  setSettings: (settings) => set({ settings })
}))
