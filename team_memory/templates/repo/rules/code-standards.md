# 代码规范

## 通用

- **不可变优先**：创建新对象，不原地修改
- **小文件优于大文件**：单文件 200–400 行，上限 800
- **错误处理完备**：try/except + 用户友好信息
- **输入校验**：用 schema（zod / pydantic）

## 提交

- Conventional Commits：`feat` / `fix` / `refactor` / `docs` / `test` / `chore`
- 小步提交，每次说明影响范围

## 测试

- 覆盖率 ≥ 80%
- TDD：先写测试（RED）→ 实现（GREEN）→ 重构

## 安全

- 无硬编码 secrets
- 所有用户输入校验
- 提交前跑 security checklist
