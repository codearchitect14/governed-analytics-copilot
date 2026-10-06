import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const STORAGE_KEY = "meridian-theme";
const CHOICES: ThemeChoice[] = ["system", "light", "dark"];

function readStored(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return CHOICES.includes(value as ThemeChoice) ? (value as ThemeChoice) : "system";
  } catch {
    // Storage can be blocked (private windows, disabled site data). Fall back to the system theme.
    return "system";
  }
}

function writeStored(value: ThemeChoice): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Ignore: the choice still applies for this page view.
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", choice);
  }
}

export function useTheme(): [ThemeChoice, (next: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => readStored());

  useEffect(() => {
    applyTheme(choice);
  }, [choice]);

  function update(next: ThemeChoice) {
    writeStored(next);
    setChoice(next);
  }

  return [choice, update];
}

export function nextTheme(current: ThemeChoice): ThemeChoice {
  return CHOICES[(CHOICES.indexOf(current) + 1) % CHOICES.length];
}
