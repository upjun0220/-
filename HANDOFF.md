# HANDOFF

## State

- Updated: 2026-08-25 · Codex
- Branch: main
- Commit: 커밋 직전
- Working tree: 이번 UI 표시 변경만 커밋 대상으로 스테이징하며 사용자 미추적 문서는 제외한다.

## Current objective

정상·낙상·협착·감전 마네킹과 설비 이상 표시를 유지하고, 판정 코드 동결 기준선을 보존한 채 시연 영상을 준비한다.

## Verified baseline

- pyflakes 경고 0건 · v1 결함 재발 54항목 실패 0건.
- 레이아웃 4해상도 잘림·겹침 0건 · 실데이터 재생 73항목 실패 0건 · 평면도 흐름 16항목 실패 0건.
- `jetson_sender.py` SHA-256 `18d2ede32dda6148c44d61a4e169cf271069d020351444c5c05169478aa76a2a` 불변.
- `verify_jetson_safe.py` SHA-256 `2c931a733651ff982d4353fb04da66eb4e90c48cba191d806ec7ecbd359e4a90` 불변.

## Next actions

1. 실제 시연 로그를 정상→과전류+협착, 정상→누설전류+감전 순서로 재생해 영상으로 기록한다.
2. 마네킹 자세를 다시 조정할 경우 정적 OBJ와 표시 변환만 수정하고 sender·판정 상수는 열지 않는다.
3. UI 수정 뒤 pyflakes와 자동 테스트 4종을 전부 다시 실행한다.

## Blockers / unknowns

- 실제 영상 촬영본에서 마네킹 가독성이 충분한지는 아직 최종 확인하지 않았다.

## Acceptance

- 정상 마네킹 최저 정점 z=0, 사고 마네킹 3종의 위치·자세 구분, 폐기 소영역 미표시.
- sender·판정 코드 해시 불변, pyflakes 0, 자동 테스트 54·0 / 레이아웃 0 / 73·0 / 16·0.
