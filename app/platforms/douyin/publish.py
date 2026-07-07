"""抖音发布入口(浏览器自动化抖音创作者服务平台 creator.douyin.com)。

抖音 PC 端上传要分片传 upload 节点 + a_bogus 签名 + create_aweme,纯 HTTP 直发链路长、
易随改版失效;发布是低频写操作,和快手一样走浏览器自动化性价比最高,也贴合本项目
「登录态浏览器 + 免手写签名」的路线:用账号专属持久 profile(已含创作者登录态)打开
发布页,上传文件、填标题/正文、点发布。

⚠️ 实验性:发布页选择器随抖音改版可能失效,集中在下面的 _* 选择器常量;
   发布时弹真实窗口,遇滑块验证 / 需补封面 / 定位话题必填可在窗口里手动处理。
   抖音视频上传后要等转码,发布按钮可点较慢,故等待给得比快手更足。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from ...browser.identity import Identity
from ...browser.manager import BrowserManager

UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
# 图文发布入口(default-tab=3 直达「发布图文」;失败再退回点 tab)
IMAGE_URL = "https://creator.douyin.com/creator-micro/content/upload?default-tab=3"
_TAB_IMAGE = ['div:has-text("发布图文")', 'text=发布图文', 'text=图文']
# 视频有独立「标题」短标题输入;图文有「作品标题」
_TITLE_SEL = ['input[placeholder*="填写作品标题"]', 'input[placeholder*="作品标题"]',
              'input[placeholder*="标题"]', '.title-input input', 'input.semi-input']
# 正文/简介富文本(抖音创作者用 editor-kit 富文本,contenteditable)
_DESC_SEL = ['.editor-kit-editor-container [contenteditable="true"]',
             'div[data-placeholder*="简介"]', 'div[contenteditable="true"]',
             '.zone-container', 'textarea[placeholder*="简介"]', 'textarea']
_PUBLISH_BTN = ['button:has-text("发布")', 'button:has-text("发布作品")',
                'div[class*="content-confirm"] button', '.publish-btn button', '.button-publish']


async def _click_first(page, selectors, timeout=2500) -> bool:
    for sel in selectors:
        try:
            await page.click(sel, timeout=timeout)
            return True
        except Exception:
            continue
    return False


async def _fill_first(page, selectors, text, timeout=2500) -> bool:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            await el.click(timeout=timeout)
            try:
                await el.fill(text, timeout=timeout)
            except Exception:
                # contenteditable 富文本 fill 不一定支持,退回键入
                await el.type(text, timeout=timeout)
            return True
        except Exception:
            try:
                await page.keyboard.type(text)
                return True
            except Exception:
                continue
    return False


async def publish_douyin(mgr: BrowserManager, identity: Identity,
                         storage_state_json: str, media_type: str, title: str,
                         desc: str, media_paths: List[str], topics: str = "",
                         headed: bool = True, timeout_seconds: int = 180
                         ) -> Tuple[bool, str, str]:
    """发布一条抖音作品。返回 (ok, result_url, error)。
    storage_state_json 仅用于校验(实际登录态在该账号持久 profile 里)。"""
    files = [str(Path(p)) for p in media_paths if p and Path(p).exists()]
    if not files:
        return False, "", "没有可用的本地媒体文件(路径不存在)"
    tags = [t.strip().lstrip("#") for t in (topics or "").split(",") if t.strip()]
    # 抖音正文 = 简介 + 话题(话题写进正文,发布时自动识别 #)
    body = ((desc or "") + ("\n" + " ".join(f"#{t}" for t in tags) if tags else "")).strip()[:2000]

    ctx = await mgr.open_headed(identity)
    page = await ctx.new_page()
    ok, result_url, error = False, "", ""
    try:
        url = IMAGE_URL if media_type == "images" else UPLOAD_URL
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)
        if "passport" in page.url or "/login" in page.url:
            return False, "", "logged_out:抖音创作平台未登录,请先在账号页点「创作者登录」"
        if media_type == "images":
            await _click_first(page, _TAB_IMAGE, timeout=2000)
            await page.wait_for_timeout(1200)
        try:
            await page.locator('input[type="file"]').first.set_input_files(
                files if media_type == "images" else files[:1], timeout=15000)
        except Exception as e:
            return False, "", f"上传文件失败: {e!r}"
        # 视频要等转码/上传;图文等缩略图渲染
        await page.wait_for_timeout(9000 if media_type == "video" else 4000)
        if title:
            await _fill_first(page, _TITLE_SEL, title.strip()[:30])
            await page.wait_for_timeout(500)
        if body:
            await _fill_first(page, _DESC_SEL, body)
        await page.wait_for_timeout(1000)
        if not await _click_first(page, _PUBLISH_BTN, timeout=4000):
            return False, "", "未找到发布按钮(发布页可能改版;或视频仍在转码,请稍后在创作平台确认)"
        # 发布成功后抖音跳到内容管理页,或弹「发布成功」
        try:
            await page.wait_for_url("**/content/manage**", timeout=20000)
            ok = True
        except Exception:
            try:
                await page.get_by_text("发布成功", exact=False).first.wait_for(timeout=8000)
                ok = True
            except Exception:
                ok = False
        result_url = page.url if ok else ""
        if not ok:
            error = "已点发布但未确认成功(请到抖音创作平台确认;视频可能仍在审核)"
    except Exception as e:
        error = f"发布异常: {e!r}"
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
    return ok, result_url, error
