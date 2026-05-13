/**
 * Inline script for root layout: mirrors frontend ThemeProvider + defaultTheme "dark"
 * and storageKey "vite-ui-theme" (see frontend/src/main.tsx, theme-provider.tsx).
 */
export const THEME_STORAGE_KEY = "vite-ui-theme"

export const themeInitScript = `(function(){try{var k=${JSON.stringify(THEME_STORAGE_KEY)};var raw=localStorage.getItem(k);var t=raw==="light"||raw==="dark"||raw==="system"?raw:"dark";var r=document.documentElement;r.classList.remove("light","dark");if(t==="system"){r.classList.add(window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");}else{r.classList.add(t);}}catch(e){document.documentElement.classList.add("dark");}})();`
