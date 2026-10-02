import traceback
from pathlib import Path
from utils.logger import setup_logger
from utils.config import get_config, get_userData
from core.msg_builder import build_message, build_message_with_openai
from core.browser import get_browser
from playwright.sync_api import Response
import time
import json


complates = {}

config = get_config()
userData = get_userData()
logger = setup_logger(level=config.get("logLevel", "Info"))
matchMode = config.get("matchMode", "nickname")


def handle_response(response: Response, userIDDict: dict):
    """
    监听用户详情接口，获取 ShortId、nickname 和 user_id
    """
    if "aweme/v1/creator/im/user_detail/" in response.url:
        try:
            json_data = response.json()

            for item in json_data.get("user_list", []):
                short_id = item.get("user", {}).get("ShortId")
                nickname = item.get("user", {}).get("nickname")
                user_id = item.get("user_id", "")

                if short_id is not None:
                    userIDDict[str(short_id)] = {
                        "nickname": nickname,
                        "user_id": user_id
                    }

        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)

            if tb:
                last = tb[-1]
                print(f"解析响应失败: {e}")
                print(
                    f"文件: {last.filename}, "
                    f"行号: {last.lineno}, "
                    f"函数: {last.name}"
                )
            else:
                print(f"解析响应失败: {e}")


def retry_operation(name, operation, retries=3, delay=2, *args, **kwargs):
    """
    通用重试逻辑
    """
    for attempt in range(retries):
        try:
            return operation(*args, **kwargs)

        except Exception as e:
            if attempt < retries - 1:
                logger.warning(
                    f"{name} 失败，正在重试第 {attempt + 1} 次，错误：{e}"
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"{name} 失败，已达到最大重试次数，错误：{e}"
                )
                raise


def scroll_and_select_user(page, account_username, targets, userIDDict):
    """
    滚动好友列表并查找目标好友。
    找到目标后 yield 好友昵称。
    """

    friends_tab_selector = (
        'xpath=//*[@id="sub-app"]/div/div/div[1]/div[2]'
    )

    target_selector = (
        'xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]'
        '//div[contains(@class, '
        '"semi-list-item-body semi-list-item-body-flex-start")]'
    )

    scrollable_friends_selector = (
        'xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]'
        '/div/div/div[3]/div/div/div/ul/div'
    )

    no_more_selector = (
        'xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]'
        '//div[contains(@class, "no-more-tip-")]'
    )

    loading_selector = (
        'xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]'
        '//div[contains(@class, "semi-spin")]'
    )

    logger.debug(
        f"账号 {account_username} 开始查找目标好友列表"
    )

    logger.debug(
        f"账号 {account_username} 目标好友列表: {targets}"
    )

    # 点击好友标签
    logger.debug(
        f"账号 {account_username} 点击进入好友标签页"
    )

    # 等待实际可操作的好友标签，不依赖主应用容器的尺寸或固定延时。
    friends_tab = page.locator(friends_tab_selector)
    friends_tab.wait_for(
        state="visible", timeout=config["browserTimeout"]
    )
    # 保留严格匹配，避免静默点击重复或过期的标签。
    friends_tab.click(timeout=config["browserTimeout"])

    # 与扫描使用相同的好友选择器，等待数据就绪后再激活列表。
    first_friend = page.locator(target_selector).first
    first_friend.wait_for(
        state="visible", timeout=config["browserTimeout"]
    )
    first_friend.click(timeout=config["browserTimeout"])

    logger.debug(
        f"账号 {account_username} 已激活好友列表，开始查找目标好友"
    )
    time.sleep(config["friendListTimeout"] / 1000)

    found_targets = set()
    remaining_targets = set(targets)

    empty_scroll_count = 0
    MAX_EMPTY_SCROLLS = 10

    while True:

        # 加载中的空列表不能算作已到底；等待可见加载提示消失。
        page.locator(loading_selector).filter(visible=True).first.wait_for(
            state="hidden", timeout=config["browserTimeout"]
        )

        target_elements = page.locator(target_selector).all()

        prev_found_count = len(found_targets)

        for element in target_elements:

            try:
                span = element.locator(
                    'xpath=.//span[contains(@class, "item-header-name-")]'
                )

                target_name = span.inner_text().strip()

                if not target_name:
                    continue

                if target_name in found_targets:
                    continue

                found_targets.add(target_name)

                logger.debug(
                    f"账号 {account_username} 找到好友 {target_name}"
                )

                # short_id 模式
                if matchMode == "short_id":

                    target_symbol = next(
                        (
                            sid
                            for sid, info in userIDDict.items()
                            if info.get("nickname") == target_name
                        ),
                        None
                    )

                # nickname 模式
                else:
                    target_symbol = target_name

                if target_symbol in targets:

                    logger.info(
                        f"账号 {account_username} "
                        f"找到目标好友: {target_name}"
                    )

                    element.click()

                    logger.info(
                        f"账号 {account_username} "
                        f"已选中好友 {target_name}"
                    )

                    yield target_name

                    if target_symbol in remaining_targets:
                        remaining_targets.remove(target_symbol)

                    if len(remaining_targets) == 0:

                        logger.info(
                            f"账号 {account_username} "
                            f"所有目标好友均已找到"
                        )

                        return

                    break

            except Exception:
                traceback.print_exc()

        else:

            new_found = len(found_targets) > prev_found_count

            if new_found:
                empty_scroll_count = 0
            else:
                empty_scroll_count += 1

            # 到达底部
            if page.locator(no_more_selector).filter(visible=True).count() > 0:

                logger.info(
                    f"账号 {account_username} "
                    f"检测到没有更多好友，已到达底部"
                )

                if remaining_targets:
                    logger.warning(
                        f"账号 {account_username} "
                        f"仍未找到: {remaining_targets}"
                    )

                break

            # 防止无限循环
            if empty_scroll_count >= MAX_EMPTY_SCROLLS:

                logger.warning(
                    f"账号 {account_username} "
                    f"连续 {MAX_EMPTY_SCROLLS} 次没有发现新好友，"
                    f"判定已到达底部"
                )

                if remaining_targets:
                    logger.warning(
                        f"账号 {account_username} "
                        f"仍未找到: {remaining_targets}"
                    )

                break

            # 找滚动容器
            scrollable_element = page.locator(
                scrollable_friends_selector
            ).element_handle()

            if scrollable_element:

                scroll_top_before = page.evaluate(
                    "(element) => element.scrollTop",
                    scrollable_element
                )

                page.evaluate(
                    "(element) => element.scrollTop += 800",
                    scrollable_element
                )

                time.sleep(0.3)

                scroll_top_after = page.evaluate(
                    "(element) => element.scrollTop",
                    scrollable_element
                )

                if scroll_top_before == scroll_top_after:

                    empty_scroll_count += 2

                    logger.debug(
                        f"账号 {account_username} "
                        f"scrollTop 未变化 "
                        f"({scroll_top_before})，"
                        f"可能已到底 "
                        f"({empty_scroll_count}/{MAX_EMPTY_SCROLLS})"
                    )

                else:

                    logger.debug(
                        f"账号 {account_username} "
                        f"滚动好友列表 "
                        f"({scroll_top_before} -> {scroll_top_after})"
                    )

                time.sleep(1.5)

            else:

                logger.error(
                    f"账号 {account_username} "
                    f"未找到滚动容器，退出"
                )

                break


def capture_page_diagnostics(page):
    """在关闭浏览器前保存诊断；诊断失败不能覆盖原始异常。"""
    try:
        root = page.locator("#sub-app")
        logger.error(
            f"失败页面 URL: {page.url}; "
            f"#sub-app 数量: {root.count()}; "
            f"首个容器可见: {root.first.is_visible()}"
        )
    except Exception as diagnostic_error:
        logger.warning(f"无法读取页面诊断: {diagnostic_error}")

    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = logs_dir / f"failure-{time.time_ns()}.png"
        page.screenshot(path=str(screenshot_path), timeout=5000)
        logger.error(f"失败页面截图: {screenshot_path}")
    except Exception as diagnostic_error:
        logger.warning(f"无法保存失败页面截图: {diagnostic_error}")


def do_user_task(browser, account_username, cookies, targets):

    context = browser.new_context()

    context.set_default_navigation_timeout(
        config["browserTimeout"]
    )

    context.set_default_timeout(
        config["browserTimeout"]
    )

    page = context.new_page()

    # 每个账号单独保存 ShortId 数据
    userIDDict = {}

    if matchMode == "short_id":

        page.on(
            "response",
            lambda response: handle_response(
                response,
                userIDDict
            )
        )

    try:

        # ---------------------------------------------------------
        # 打开抖音创作者中心
        # ---------------------------------------------------------

        retry_operation(
            "打开抖音创作者中心",
            page.goto,
            retries=config["taskRetryTimes"],
            delay=5,
            url="https://creator.douyin.com/",
        )

        # ---------------------------------------------------------
        # 注入 Cookie
        # ---------------------------------------------------------

        playwright_cookies = []

        for cookie in cookies:

            converted_cookie = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie.get("path", "/"),
                "secure": cookie.get("secure", False),
                "httpOnly": cookie.get("httpOnly", False),
            }

            same_site = cookie.get("sameSite")

            if same_site in ["lax", "strict", "none"]:
                converted_cookie["sameSite"] = same_site

            playwright_cookies.append(converted_cookie)

        context.add_cookies(playwright_cookies)

        logger.debug(
            f"账号 {account_username} Cookie 注入完成"
        )

        # ---------------------------------------------------------
        # 打开消息页面
        # ---------------------------------------------------------

        retry_operation(
            "导航到消息页面",
            page.goto,
            retries=config["taskRetryTimes"],
            delay=5,
            url="https://creator.douyin.com/creator-micro/data/following/chat",
        )

        logger.debug(
            f"账号 {account_username} 开始查找目标好友"
        )

        # ---------------------------------------------------------
        # 查找并发送消息
        # ---------------------------------------------------------

        for target_username in scroll_and_select_user(
            page,
            account_username,
            targets,
            userIDDict
        ):

            logger.info(
                f"账号 {account_username} "
                f"已选中好友 {target_username}"
            )

            # -----------------------------------------------------
            # 等待聊天输入框
            # -----------------------------------------------------

            chat_input_selector = (
                "xpath=//div[contains(@class, 'chat-input-')]"
            )

            page.wait_for_selector(
                chat_input_selector,
                timeout=config["browserTimeout"]
            )

            chat_input = page.locator(
                chat_input_selector
            )

            # -----------------------------------------------------
            # 点击输入框
            # -----------------------------------------------------

            chat_input.click()

            # -----------------------------------------------------
            # 创建消息
            # -----------------------------------------------------

            message = build_message()

            logger.info(
                f"账号 {account_username} "
                f"准备发送消息给好友 {target_username}：\n"
                f"{message}"
            )

            # -----------------------------------------------------
            # 输入消息
            # -----------------------------------------------------

            lines = message.splitlines()

            for index, line in enumerate(lines):

                chat_input.type(line)

                # 最后一行不需要换行
                if index < len(lines) - 1:
                    chat_input.press("Shift+Enter")

            # -----------------------------------------------------
            # 等待输入完成
            # -----------------------------------------------------

            time.sleep(0.5)

            logger.info(
                f"账号 {account_username} "
                f"消息已输入，准备发送"
            )

            # -----------------------------------------------------
            # 按 Enter 发送
            # -----------------------------------------------------

            chat_input.press("Enter")

            logger.info(
                f"账号 {account_username} "
                f"已按下 Enter，等待消息发送完成"
            )

            time.sleep(3)

            logger.info(
                f"账号 {account_username} "
                f"给好友 {target_username} "
                f"发送消息流程完成"
            )

    except Exception as e:

        logger.error(
            f"账号 {account_username} 执行任务时发生错误: {e}"
        )

        capture_page_diagnostics(page)
        traceback.print_exc()

        raise

    finally:

        context.close()


def runTasks():

    playwright, browser = get_browser()

    try:

        logger.info("开始执行任务")

        logger.debug("当前配置如下：")

        logger.debug(
            f"消息模板: "
            f"{config.get('messageTemplate', '未找到消息模板')}"
        )

        logger.debug(
            f"一言类型: {config['hitokotoTypes']}"
        )

        for user in userData:

            logger.debug(
                f"用户: {user.get('username', '未知用户')}, "
                f"目标好友: {user['targets']}"
            )

        # ---------------------------------------------------------
        # 逐个账号执行
        # ---------------------------------------------------------

        for user in userData:

            cookies = user["cookies"]
            targets = user["targets"]

            complates[user["unique_id"]] = []

            account_username = user.get(
                "username",
                "未知用户"
            )

            logger.info(
                f"开始处理账号 {account_username}"
            )

            do_user_task(
                browser,
                account_username,
                cookies,
                targets
            )

            logger.info(
                f"账号 {account_username} 任务完成"
            )

    finally:

        browser.close()
        playwright.stop()
