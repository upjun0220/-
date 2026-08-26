# HANDOFF

## State

- Updated: 2026-08-26 · Codex
- Branch: main
- Commit: 커밋 직전
- Working tree: R2 시연 기준선 코드와 인계 문서만 커밋하며 사용자 문서·분석 출력·백업 JSON은 제외한다.

## Current objective

영상 시연용 R2 협착 판정을 유지하면서 신규 사람의 정상 동작 오탐을 계측한다.

## Verified baseline

- 판정 이식 9,580건 불일치 0건 · 젯슨 안전성 102항목 실패 0건.
- 기존 R2 전체 라벨 재현 44/60 · 오탐 12/105이며 R2-new는 오탐 51/105로 폐기했다.
- 상황 해소 시 PINCH 창 초기화 · 후속 R2 critical 억제 · 차단 유지 15초 무동작 warning을 실장비에서 확인했다.
- 젯슨 sender SHA-256 `afb5470a1e9e77ee87f4b38fc45ea5dbaaf93cebb5786a2aca8361e421361ac8`이며 parser·sender·사용자 UI와 PC 관제 UI가 실행 중이다.

## Next actions

1. 승원·성준·민석·재국의 정상 서기·걷기·일반 웅크리기를 동일 게이트에서 동작별 시작·종료 마커와 함께 수집한다.
2. `throttled=true`인 균등 표본으로 legacy·R2의 사람별 재현율과 동작별 오탐률을 재계산한다.
3. 영상 시연 뒤 R2 운영 유지 여부를 사용자 승인으로 확정하고 새 기준선을 문서 정본에 반영한다.

## Blockers / unknowns

- 신규 4명의 정상 동작 음성 자료가 없어 현재 R2의 사람 일반화 오탐률을 알 수 없다.

## Acceptance

- 상황 해소 뒤 pinching critical 재발화 0건이며, 차단 유지·재실 무동작은 15초 warning만 발생한다.
- 신규 사람 음성 자료에서 걷기 오탐률 10% 이하를 확인하기 전 일반화 성능을 주장하지 않는다.
