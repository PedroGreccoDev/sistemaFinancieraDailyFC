import { useEffect, useState } from 'react'

export function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    // Por defecto modo claro; solo respeta lo que el usuario eligió antes.
    return localStorage.getItem('theme') === 'dark'
  })

  useEffect(() => {
    const root = document.documentElement
    if (dark) {
      root.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      root.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
    // Sincroniza la barra del navegador en mobile (iOS Safari) con el fondo
    // del tema, para que no quede oscura al pasar a modo claro.
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', dark ? '#080810' : '#ebe4d6')
  }, [dark])

  return [dark, () => setDark((d) => !d)]
}
