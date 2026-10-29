---
name: QMS+MES
description: 회색 틀 안에 흰 업무 면을 두고, 누를 수 있는 것에만 파랑 한 가지를 쓰는 사내 품질·생산 업무 화면.
colors:
  primary: "#0057d2"
  primary-deep: "#0040b0"
  on-primary: "#ffffff"
  band-blue: "#ebf8ff"
  canvas: "#ffffff"
  chrome: "#f5f6f7"
  band: "#eaecee"
  ink: "#000000"
  ink-body: "#223548"
  ink-list: "#354a5f"
  ink-meta: "#475e75"
  ink-nav: "#545454"
  hairline: "#475e75"
  positive: "#256f3a"
  positive-bg: "#f5fae5"
  critical: "#a33f00"
  critical-bg: "#fff8d6"
  negative: "#aa0808"
  negative-bg: "#ffeaf4"
  dark-canvas: "#12171c"
  dark-chrome: "#1d232a"
  dark-primary: "#6bc0ff"
typography:
  page-title:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 500
    lineHeight: "35.2px"
    letterSpacing: "0"
  lead:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 500
    lineHeight: "30.8px"
    letterSpacing: "0"
  subhead:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 500
    lineHeight: "22px"
    letterSpacing: "0"
  body:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: "27px"
    letterSpacing: "0"
  button:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 500
    lineHeight: "17.6px"
    letterSpacing: "0"
  field:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: "24px"
    letterSpacing: "0"
  nav-link:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: "21px"
    letterSpacing: "0"
  list-item:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 350
    lineHeight: "21px"
    letterSpacing: "0"
  caption:
    fontFamily: "Segoe UI, Malgun Gothic, Apple SD Gothic Neo, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 500
    lineHeight: "21px"
    letterSpacing: "0"
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
spacing:
  sm: "8px"
  md: "9px"
  xl: "12px"
  wide: "16px"
  section: "20px"
  giant: "24px"
  max: "32px"
  huge: "40px"
  band: "56px"
components:
  shell-bar:
    backgroundColor: "{colors.chrome}"
    textColor: "{colors.ink-nav}"
    typography: "{typography.nav-link}"
    height: "60px"
  side-nav-link:
    backgroundColor: "{colors.chrome}"
    textColor: "{colors.ink-nav}"
    typography: "{typography.nav-link}"
    rounded: "{rounded.md}"
    padding: "9px 12px"
  side-nav-link-current:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "12px 14px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
  button-outline:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.primary-deep}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "12px 14px"
    height: "44px"
  button-outline-hover:
    backgroundColor: "{colors.band-blue}"
  button-field:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
    height: "58px"
  text-field:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-body}"
    typography: "{typography.field}"
    rounded: "{rounded.md}"
    padding: "9px 12px"
    height: "44px"
  card:
    backgroundColor: "{colors.canvas}"
    rounded: "{rounded.md}"
    padding: "{spacing.giant}"
  kpi-tile:
    backgroundColor: "{colors.chrome}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.section}"
  status-badge:
    typography: "{typography.caption}"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
  table-cell:
    textColor: "{colors.ink-list}"
    typography: "{typography.list-item}"
    padding: "12px 16px"
  table-header:
    textColor: "{colors.ink-meta}"
    typography: "{typography.caption}"
---

# Design System: QMS+MES

## Overview

**Creative North Star: "현장의 업무 창 (The Plant Window)"**

화면은 홍보물이 아니라 업무를 담는 창이다. 연한 회색 틀(상단 바 60px와 왼쪽 메뉴)이 창틀 역할을 하고, 그 안의 흰 면에 기록과 할 일이 놓인다. 틀은 회색 글자로 조용히 물러나 있고, 사용자의 눈은 흰 면 위의 기록으로 간다. 기준은 SAP 웹 디자인 분석(`DESIGN-sap.md`)이다. 이 시스템은 그 구조와 수치를 업무 화면에 옮겨 쓴다.

색은 거의 쓰지 않는다. 흰색이 바탕, 회색 두 단계(틀·띠)가 구조를 맡고, 파랑 한 가지가 "누를 수 있다"는 뜻만 맡는다. 품질 상태(정상·주의·이상)는 녹색·주황·빨강으로 따로 표시하며, 파랑과 섞어 쓰지 않는다. 깊이는 그림자가 아니라 평평한 면의 색 차이로 만든다.

글자는 SAP 수치를 그대로 쓴다. 본문 18px, 페이지 제목 32px다. 크기가 비슷한 글자끼리는 굵기로 구분한다. 메뉴 글자는 15px·400 회색이고, 표 칸 글자는 15px·350 slate다.

**Key Characteristics:**
- 회색 틀(`chrome`) + 흰 업무 면(`canvas`)의 2층 구조
- 파랑 한 가지(`primary`)는 버튼·링크·현재 메뉴에만 쓴다
- 제목은 검정, 본문은 slate, 틀은 중립 회색. 색상 계열이 바뀌면서 위계가 생긴다
- 그림자 없음. 카드는 얇은 띠색 테두리, KPI 타일은 회색 면
- 모서리는 컨트롤 8px, 사진 12px, 배지 4px. 알약 모양은 쓰지 않는다
- 오프라인 시스템 글꼴, 자간 0

## Colors

흰 바탕에 회색 두 단계와 파랑 하나. 상태색 세 가지는 의미가 있을 때만 쓴다.

### Primary
- **누름 파랑 (Action Blue)** (`primary`): 채운 버튼, 텍스트 링크, 현재 메뉴 글자, 입력 포커스 링, 타임라인 공정 선, SPC 중심선. 이 색이 보이면 누를 수 있거나 지금 선택된 것이다.
- **눌린 파랑 (Pressed Blue)** (`primary-deep`): 버튼 hover·눌림, 외곽선 버튼 글자.
- **연한 파랑 띠 (Selection Wash)** (`band-blue`): 선택된 행, 검색 결과 hover, 외곽선 버튼 hover, 텍스트 선택 배경.

### Neutral
- **업무 면 (Canvas)** (`canvas`): 본문 바탕, 카드, 입력칸.
- **창틀 회색 (Chrome)** (`chrome`): 상단 바, 사이드바, KPI 타일, 저장 줄, 표 행 hover.
- **띠 회색 (Band)** (`band`): 카드 테두리, 표 줄 구분선, 사이드바 hover.
- **제목 검정 (Ink)** (`ink`): 페이지·카드 제목, KPI 숫자.
- **본문 slate (Ink Body)** (`ink-body`): 본문, 입력값.
- **목록 slate (Ink List)** (`ink-list`): 표 칸, 검색 결과.
- **보조 slate (Ink Meta)** (`ink-meta`): 표 머리, 캡션, 도움말, 사이드바 그룹 제목. 같은 값을 입력칸·외곽선 버튼 테두리(`hairline`)에도 쓴다.
- **틀 회색 글자 (Ink Nav)** (`ink-nav`): 메뉴, 경로(breadcrumb), 사용자 메뉴. 본문에는 쓰지 않는다.

### Status
- **정상** (`positive` / `positive-bg`), **주의** (`critical` / `critical-bg`), **이상** (`negative` / `negative-bg`): 배지, 판정 배너, KPI 숫자, SPC 관리한계·경보점. 주의 글자색은 `#a33f00`이다. 노란 배경 위에서 AA 대비(4.5:1)를 맞추려고 SAP 주황을 어둡게 했다.

### Dark
다크 모드는 `dark-canvas` 바탕, `dark-chrome` 틀, `dark-primary`(밝은 하늘 파랑) 누름 색으로 같은 구조를 유지한다. 대비는 라이트와 같은 AA 기준이다.

### Named Rules
**The One Blue Rule.** 파랑은 누를 수 있는 것과 현재 위치에만 쓴다. 장식, 제목, 아이콘 바탕에 파랑을 칠하지 않는다.
**The Status Is Not Brand Rule.** 품질 상태는 녹색·주황·빨강만 쓴다. 파랑으로 상태를 표시하지 않는다(정보 배지 하나는 예외).

## Typography

**Body Font:** Segoe UI (Malgun Gothic → Apple SD Gothic Neo → system-ui)
**Display Font:** 같은 글꼴. 두 번째 글꼴과 고정폭 글꼴은 쓰지 않는다.

**Character:** SAP의 "72" 글꼴은 사내 전용이고, 이 시스템은 외부 폰트를 내려받지 않는다. 그래서 Windows 기본 글꼴로 대신한다. 굵기 350·500은 Segoe UI Semilight/Semibold가 맡는다. 한글은 Malgun Gothic에 해당 굵기가 없으면 가장 가까운 굵기로 표시된다.

### Hierarchy
- **Page Title** (500, 32px, 35.2px): 화면마다 하나 있는 h1. 모바일(767px 이하)에서는 28px.
- **Lead** (500, 28px, 30.8px): 검사 판정 배너(합격/불합격).
- **Subhead** (500, 20px, 22px): 카드·모듈 제목, 로고 옆 시스템 이름.
- **Body** (400, 18px, 27px): 본문 기본. 현장 검사 화면은 20px/30px로 키운다.
- **Button** (500, 16px, 17.6px): 버튼과 상단 도구 버튼.
- **Field** (400, 16px, 24px): 입력칸 값과 placeholder.
- **Nav Link** (400, 15px, 21px): 사이드바, 경로, 사용자 메뉴.
- **List Item** (350, 15px, 21px): 표 칸, 타임라인, 검색 결과.
- **Caption** (500, 14px, 21px): 표 머리, 배지, 도움말(도움말은 400).

### Named Rules
**The Weight-Not-Size Rule.** 15px 글자 두 종류는 크기가 아니라 굵기와 색으로 나눈다. 메뉴는 400 회색, 표 칸은 350 slate다. 굵기를 400·700 두 가지로 줄이지 않는다.
**The Zero Tracking Rule.** 자간은 어디에서나 0이다. 대문자 라벨이나 넓은 자간 라벨을 쓰지 않는다.

## Layout

- **틀:** 상단 바(높이 60px, 좌우 여백 24px)와 왼쪽 사이드바(240px)가 회색 창틀이 된다. 본문은 `.main > .content`가 남은 폭을 채운다. 넓은 표가 화면을 밀어내지 않도록 그 안에서 가로로 스크롤된다.
- **여백 리듬:** 본문 여백은 위 24px, 좌우 32px, 아래 56px다. 카드 간격은 24px, 카드 안쪽은 24px(모바일 16px), KPI 타일 간격은 16px다. 제목 아래 24px를 둔다.
- **그리드:**
  - 대시보드는 1100px 이상에서 4칸 × 최대 10줄(줄 높이 10rem, 간격 16px) 격자다. 보통 위젯은 1×1, 넓은 위젯은 2×2 칸을 차지하고 저장된 칸에 놓인다. 그보다 좁으면 2칸으로 저장 순서대로 흐른다.
  - 카드 묶음은 `minmax(24rem, 1fr)`, KPI 타일은 `minmax(12rem, 1fr)`이다.
- **화면 폭 단계:**
  - 960px 미만: 사이드바가 "메뉴" 버튼으로 접히고, 타임라인이 세로로 쌓인다.
  - 767px 이하: 대시보드가 한 줄로 쌓인다(위→아래, 왼→오른쪽 순서). 검색칸은 로고 아래 한 줄을 차지하고, 본문 여백은 16px로 줄어든다.
- **터치:** 버튼과 입력칸은 높이 44px 이상이다. 현장 검사 화면은 입력칸 56px, 버튼 58px다.

## Elevation & Depth

이 시스템은 평평하다. 버튼, 카드, 상단 바, 메시지에는 그림자가 없다. 깊이는 면의 색 차이로 만든다: 흰 업무 면 → 회색 창틀·KPI 타일 → 띠색 테두리.

### Shadow Vocabulary
- **떠 있는 목록** (`box-shadow: 0 8px 24px rgba(34, 53, 72, .12)`): 통합 검색 결과 목록 하나에만 쓴다. 본문 위에 겹쳐 뜨는 유일한 면이라서 그림자가 필요하다.

### Named Rules
**The Flat Frame Rule.** 그림자는 본문 위에 겹쳐 뜨는 임시 목록에만 허용한다. 카드나 버튼을 그림자로 띄우지 않는다.

## Shapes

모서리는 짧은 단계에서 멈춘다.
- 4px(`sm`): 상태 배지, 타임라인 사진, KPI 막대.
- 8px(`md`): 버튼, 입력칸, 카드, KPI 타일, 메뉴 항목, 메시지.
- 12px(`lg`): 큰 사진 틀.

상단 바, 사이드바, 저장 줄처럼 화면 폭을 차지하는 면은 각지게(0) 둔다. 알약 모양과 원형은 쓰지 않는다.

강조 선은 타임라인 카드 위쪽 3px 선 하나뿐이다. 공정은 파랑, 부적합은 빨강이다. 카드나 알림의 왼쪽에 굵은 색 선을 넣지 않는다.

## Components

### Buttons
- **Shape:** 8px 모서리, 높이 44px, 안쪽 여백 12px 14px.
- **Primary:** 파랑 바탕에 흰 글자, 16px·500. hover 때 진한 파랑으로 바뀐다. 비활성은 투명도 45%에 `not-allowed` 커서.
- **Outline (`.ghost`, 상단 도구 버튼):** 흰 바탕, 보조 slate 테두리, 진한 파랑 글자. hover 때 연한 파랑 띠와 진한 파랑 테두리.
- **Field (검사 입력):** 높이 58px, 안쪽 여백 16px 20px, 18px. 장갑 낀 손가락용.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** 흰 업무 면, 1px 띠 회색 테두리, 그림자 없음.
- **Internal Padding:** 24px(모바일 16px). 제목은 20px·500 검정. 안의 표가 넓으면 카드 안에서 가로로 스크롤된다.
- **KPI Tile:** 회색 창틀 면, 테두리 없음, 안쪽 여백 20px. 제목 15px·500, 설명 14px 보조 slate, 숫자 36px·500. 상태(정상·주의·이상)는 숫자 색으로 표시한다.

### Inputs / Fields
- **Style:** 흰 바탕, 1px 보조 slate 테두리, 8px 모서리, 높이 44px, 16px 글자. placeholder는 보조 slate(불투명).
- **Hover:** 창틀 회색 바탕.
- **Focus:** 2px 파랑 외곽선, 1px 띄움. 커서(caret)와 체크박스 색도 파랑이다.
- **Error:** 오류 문구와 오류 상자는 이상 빨강 글자, 연분홍 바탕, 1px 빨강 테두리.

### Navigation
- **상단 바:** 회색 창틀, 60px. 로고(없으면 파랑 "Q" 상자와 "QMS+MES"), 통합 검색(Ctrl+K), 오른쪽 끝 사용자 메뉴(15px 회색)가 있다.
- **사이드바:** 회색 창틀, 240px. 그룹 제목은 14px·500 보조 slate. 항목은 15px 회색 글자, 9px 12px 여백, 8px 모서리. hover 때 띠 회색 바탕과 검정 글자. 현재 화면은 흰 바탕, 파랑 글자 500, 1px 띠색 안쪽 테두리. QMS·MES 구분 대신 상용 제품의 모듈 순서(홈·기준정보·생산·품질검사·부적합·조치·고객·협력사·계측기·심사·문서·변경·교육·분석·관리·개인)로 묶는다(`core/nav.py`, 근거 `docs/menu-benchmark.md`). 전체 메뉴는 "관리" 묶음에 있다.
- **모바일:** 960px 미만에서 사이드바가 높이 44px의 "메뉴" 버튼으로 접힌다. 버튼은 회색 틀 그대로이며 파랑으로 칠하지 않는다.
- **경로(breadcrumb):** 15px 회색. 링크는 파랑이고, hover 때만 밑줄이 생긴다.

### Status Badge
4px 모서리, 1px 같은 색 테두리, 14px·500, 2px 8px 여백. 정상·주의·이상·정보·중립 다섯 종류가 있다. 글자가 상태 이름을 직접 말하므로 색만으로 전달하지 않는다.

### Tables
- 머리: 14px·500 보조 slate, 1px 보조 slate 아래 선.
- 칸: 15px·350 목록 slate, 12px 16px 여백, 1px 띠 회색 줄 구분.
- 행 hover: 창틀 회색. 숫자 칸은 오른쪽 정렬에 고정폭 숫자(tabular-nums).

### LOT Timeline (Signature)
공정 순서대로 가로로 놓인 회색 카드 줄이다. 카드 위쪽 3px 선은 공정이면 파랑, 부적합이면 빨강이다. 시간은 14px 보조 slate, 사진 썸네일은 64px에 4px 모서리. 960px 미만에서는 세로로 쌓인다.

## Do's and Don'ts

### Do:
- **Do** 파랑(`#0057d2`)은 버튼·링크·현재 메뉴·포커스에만 쓴다.
- **Do** 구역은 회색 면(`#f5f6f7`)이나 1px 띠색 선(`#eaecee`)으로 나눈다.
- **Do** 제목은 검정, 본문은 slate(`#223548`), 틀은 회색(`#545454`)으로 색 계열을 나눈다.
- **Do** 버튼·입력칸은 높이 44px 이상, 현장 화면은 56~58px로 만든다.
- **Do** 새 색은 `core/static/qms/fiori.css`의 `--f-*` 토큰으로만 추가하고, 다크 모드 값도 함께 정의한다.
- **Do** 글자 대비는 라이트·다크 모두 4.5:1 이상을 지킨다.

### Don't:
- **Don't** 카드, 버튼, 상단 바에 그림자를 넣지 않는다.
- **Don't** 카드·알림·목록 항목의 왼쪽이나 오른쪽에 1px보다 굵은 색 선을 넣지 않는다.
- **Don't** 알약 모양(완전히 둥근) 배지나 버튼을 만들지 않는다. 배지는 4px다.
- **Don't** 본문에 틀 회색(`#545454`)을 쓰지 않는다. 그 색은 메뉴·경로 전용이다.
- **Don't** 자간을 넣거나 대문자 라벨을 쓰지 않는다.
- **Don't** 외부 글꼴·아이콘·CDN을 불러오지 않는다. 오프라인에서 동작해야 한다.
- **Don't** 파랑이나 두 번째 강조색을 장식에 쓰지 않는다.
