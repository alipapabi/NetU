# NetU Inline Auth Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为预览、下载、删除三类操作实现统一页面内密码弹窗，并按文件类型区分当前页预览与新页面预览。

**Architecture:** 保持现有 `preview / download / delete` 能力模型不变，新增一个轻量 JSON 能力验证接口供前端弹窗调用。前端把三类操作统一收敛到一个动作调度器，根据文件类型决定当前页弹层预览、新页预览或浏览器下载。

**Tech Stack:** Python 3, Flask, Jinja2, Vanilla JavaScript, pytest

---

## 文件结构映射

- Modify: `d:\CODE\downcent\netu_app\main_routes.py`
- Modify: `d:\CODE\downcent\netu_app\templates\index.html`
- Modify: `d:\CODE\downcent\netu_app\static\app.js`
- Modify: `d:\CODE\downcent\netu_app\static\app.css`
- Modify: `d:\CODE\downcent\tests\test_routes.py`
- Modify: `d:\CODE\downcent\tests\test_assets.py`

### Task 1: 能力验证接口

**Files:**
- Modify: `d:\CODE\downcent\netu_app\main_routes.py`
- Test: `d:\CODE\downcent\tests\test_routes.py`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 新增 JSON 能力验证接口，返回成功/失败 JSON，不破坏现有表单登录**
- [ ] **Step 4: 运行测试确认通过**

### Task 2: 统一密码弹窗与动作调度

**Files:**
- Modify: `d:\CODE\downcent\netu_app\templates\index.html`
- Modify: `d:\CODE\downcent\netu_app\static\app.js`
- Modify: `d:\CODE\downcent\netu_app\static\app.css`
- Test: `d:\CODE\downcent\tests\test_assets.py`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现统一弹窗、动作模式切换、密码提交、错误提示**
- [ ] **Step 4: 运行测试确认通过**

### Task 3: 预览/下载分流与回归

**Files:**
- Modify: `d:\CODE\downcent\netu_app\static\app.js`
- Modify: `d:\CODE\downcent\tests\test_routes.py`
- Modify: `d:\CODE\downcent\tests\test_assets.py`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现轻内容当前页弹层预览、复杂内容新页预览、下载触发浏览器下载器**
- [ ] **Step 4: 运行全量回归**

## 自检

- 已覆盖统一弹窗、预览分流、下载触发和删除沿用能力 cookie
- 未包含与本次无关的后端权限模型重构
