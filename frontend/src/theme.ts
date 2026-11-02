import { theme as antdTheme, type ThemeConfig } from 'antd'
import { useEffect, useState } from 'react'

// core/static/qms/fiori.css 의 :root 값(라이트·다크)을 antd 토큰으로 옮긴 것이다. 색을 바꾸면 fiori.css 와 같이 고친다.
const FONT = '"Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif'

const light = {
  colorPrimary: '#0057d2', colorLink: '#0057d2', colorInfo: '#0057d2',
  colorBgBase: '#ffffff', colorBgLayout: '#f5f6f7', colorBgContainer: '#ffffff',
  colorText: '#223548', colorTextSecondary: '#475e75', colorTextHeading: '#000000',
  colorBorder: '#eaecee', colorBorderSecondary: '#eaecee',
  colorTextLightSolid: '#fff', shell: '#f5f6f7', nav: '#545454', selected: '#ebf8ff', colorSuccess: '#256f3a', colorWarning: '#a33f00', colorError: '#aa0808',
}

const dark = {
  colorPrimary: '#6bc0ff', colorLink: '#6bc0ff', colorInfo: '#6bc0ff',
  colorBgBase: '#12171c', colorBgLayout: '#1d232a', colorBgContainer: '#12171c',
  colorText: '#eaecee', colorTextSecondary: '#a9b4be', colorTextHeading: '#ffffff',
  colorBorder: '#2d3540', colorBorderSecondary: '#2d3540',
  colorTextLightSolid: '#0b1b2b', shell: '#1d232a', nav: '#c4cbd2', selected: '#13304a', colorSuccess: '#6bd28c', colorWarning: '#ffab52', colorError: '#ff8a8a',
}

const query = window.matchMedia('(prefers-color-scheme: dark)')

export function useAppTheme(): ThemeConfig {
  const [isDark, setDark] = useState(query.matches)
  useEffect(() => {
    const on = (e: MediaQueryListEvent) => setDark(e.matches)
    query.addEventListener('change', on)
    return () => query.removeEventListener('change', on)
  }, [])

  const { shell, nav, selected, ...token } = isDark ? dark : light
  useEffect(() => {
    document.body.style.margin = '0'
    document.body.style.background = token.colorBgBase
    document.body.style.color = token.colorText
  }, [isDark])

  return {
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: { ...token, fontFamily: FONT, borderRadius: 8 },
    // antd 기본 상단 바·사이드바는 남색이라 fiori.css 의 셸 색(--f-shell, --f-nav)으로 덮는다.
    components: {
      Layout: { headerBg: shell, headerColor: nav, siderBg: shell, lightSiderBg: shell, triggerBg: shell, lightTriggerBg: shell, triggerColor: nav },
      Menu: { itemBg: shell, subMenuItemBg: shell, itemColor: nav, itemSelectedBg: selected, itemSelectedColor: token.colorPrimary },
    },
  }
}
