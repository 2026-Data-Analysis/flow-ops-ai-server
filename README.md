# FlowOps AI Server

FlowOps QA/QC 자동화 시스템의 AI 서버.
멀티 에이전트 구조로 시나리오 테스트, 테스트 케이스 생성, 장애 대응을 지원.

## 실행

\`\`\`bash
# 1) 의존성 설치
pip install -r requirements.txt

# 2) 환경변수 설정
cp .env.example .env
# .env 파일을 열어 FLOWOPS_ANTHROPIC_API_KEY 입력

# 3) 서버 실행
uvicorn app.main:app --reload --port 8000
\`\`\`

## API 문서
서버 실행 후 http://localhost:8000/docs 접속.

## 폴더 구조
자세한 구조는 `PROJECT_STRUCTURE.md` 참조.