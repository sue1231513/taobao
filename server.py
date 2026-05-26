"""
淘宝MCP服务器 - MCP套MCP架构 (加固版)
外层: FastMCP HTTP服务器（部署在Zeabur）
内层: 通过 stdio_filter.py wrapper 调用 sinataoke_cn，过滤噪音日志
 
加固措施:
1. 所有对 sinataoke 的调用经过 stdio_filter.py 过滤 stdout 噪音
2. 锁定 sinataoke_cn 版本到 2.0.5, 防止作者推破坏性更新
3. 全局 asyncio.Lock 确保同时只有一个 sinataoke 子进程运行, 防止 CPU 爆炸
4. 45 秒调用超时, 卡住的子进程会被自动清理
"""
import os
import sys
import json
import asyncio
from fastmcp import FastMCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
 
sys.stdout.reconfigure(line_buffering=True)
 
port = int(os.getenv("PORT", 8080))
 
# 创建外层MCP服务器
mcp = FastMCP(
    name="淘宝导购MCP服务器",
    instructions="帮助转换淘宝返利链接和搜索商品",
)
 
# 淘宝客凭证（从环境变量读取，不含默认值）
TAOBAO_SESSION = os.environ["TAOBAO_SESSION"]
TAOBAO_PID = os.environ["TAOBAO_PID"]
 
# 锁定 sinataoke_cn 版本, 防止作者推破坏性更新
SINATAOKE_VERSION = "2.0.5"
 
# 全局锁: 确保同时只有一个 sinataoke 子进程在跑
_call_lock = asyncio.Lock()
 
# 单次调用总超时(秒)
CALL_TIMEOUT = 45.0
 
# 搜索默认返回条数
DEFAULT_COUNT = 30
 
 
def _parse_search_result(raw: str, count: int) -> str:
    """
    从 sinataoke 原始 JSON 中提取关键字段，大幅压缩体积。
    每条只保留: 标题、最终价、原价、促销标签、店铺名、返利链接
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
 
    items = (
        data.get("result_list", {})
            .get("map_data", [])
    )
 
    results = []
    for item in items[:count]:
        basic = item.get("item_basic_info", {})
        price_info = item.get("price_promotion_info", {})
        publish = item.get("publish_info", {})
 
        title = basic.get("title", "")
        shop = basic.get("shop_title", "")
        final_price = price_info.get("final_promotion_price", "")
        original_price = price_info.get("zk_final_price", "")
 
        tags = [
            t.get("tag_name", "")
            for t in price_info.get("promotion_tag_list", {})
                                .get("promotion_tag_map_data", [])
            if t.get("tag_name")
        ]
        promo = "、".join(tags) if tags else ""
 
        click_url = publish.get("click_url", "")
        if click_url and click_url.startswith("//"):
            click_url = "https:" + click_url
 
        results.append(
            f"【{title}】\n"
            f"  店铺：{shop}\n"
            f"  价格：¥{final_price}（原价¥{original_price}）\n"
            f"  促销：{promo or '无'}\n"
            f"  链接：{click_url}"
        )
 
    total = data.get("total_results", "?")
    header = f"共找到 {total} 件，展示前 {len(results)} 条：\n\n"
    return header + "\n\n".join(results)
 
 
def _get_taobao_mcp_params() -> StdioServerParameters:
    """构建通过 stdio_filter.py 间接启动 sinataoke 的参数"""
    mcp_env = os.environ.copy()
    mcp_env.pop("TAOBAO_APP_KEY", None)
    mcp_env.pop("TAOBAO_APP_SECRET", None)
    mcp_env["ENV_URL"] = "https://config.sinataoke.cn/api/mcp/secret"
    mcp_env["ENV_SECRET"] = "url:mcp.sinataoke.cn"
    mcp_env["ENV_OVERRIDE"] = "false"
    mcp_env["TAOBAO_SESSION"] = TAOBAO_SESSION
    mcp_env["TAOBAO_PID"] = TAOBAO_PID
    mcp_env["PDD_CLIENT_ID"] = "disable"
    mcp_env["PDD_CLIENT_SECRET"] = "disable"
    mcp_env["PDD_SESSION_TOKEN"] = "disable"
    mcp_env["JD_APP_KEY"] = "disable"
    mcp_env["JD_APP_SECRET"] = "disable"
    mcp_env["SINATAOKE_VERSION"] = SINATAOKE_VERSION
    return StdioServerParameters(
        command="python3",
        args=["/app/stdio_filter.py"],
        env=mcp_env,
    )
 
 
async def _call_sinataoke_tool(tool_name: str, args: dict) -> str:
    async with _call_lock:
        try:
            return await asyncio.wait_for(
                _do_call(tool_name, args),
                timeout=CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"调用 {tool_name} 超时({CALL_TIMEOUT}秒), 子进程已被清理"
            )
 
 
async def _do_call(tool_name: str, args: dict) -> str:
    server_params = _get_taobao_mcp_params()
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)
            if result.content and len(result.content) > 0:
                return result.content[0].text
            return ""
 
 
@mcp.tool()
async def convert_taobao_link(url: str) -> str:
    """
    转换淘宝商品链接为返利链接。
    传入淘宝/天猫商品URL，返回专属返利推广链接。
 
    Args:
        url: 淘宝或天猫商品URL
    """
    try:
        text = await _call_sinataoke_tool(
            "taobao.convertLink", {"material_list": url}
        )
        if text:
            return f"转换成功！专属返利链接：\n{text}"
        return "转换失败，淘客系统没有返回有效数据。"
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "exceptions"):
            err_msg = " | ".join([str(exc) for exc in e.exceptions])
        return f"淘客链接转换服务异常: {err_msg}"
 
 
@mcp.tool()
async def search_taobao_products(keyword: str, count: int = DEFAULT_COUNT) -> str:
    """
    搜索淘宝商品并返回带返利链接的商品列表。
    每条只返回标题、价格、促销标签、店铺、返利链接，保持上下文精简。
 
    Args:
        keyword: 搜索关键词，比如"连衣裙"、"蓝牙耳机"
        count: 返回条数，默认30，最多不超过sinataoke单次返回量
    """
    try:
        text = await _call_sinataoke_tool(
            "taobao.searchMaterial", {"q": keyword}
        )
        if not text:
            return f"没有搜到关于 {keyword} 的合适商品。"
        return _parse_search_result(text, count)
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "exceptions"):
            err_msg = " | ".join([str(exc) for exc in e.exceptions])
        return f"导购搜索服务异常: {err_msg}"
 
 
@mcp.tool()
async def get_server_info() -> str:
    """获取服务器信息"""
    return (
        f"淘宝导购MCP服务器运行中\n"
        f"sinataoke版本: {SINATAOKE_VERSION} (已锁定)\n"
        f"调用超时: {CALL_TIMEOUT}秒\n"
        f"并发模式: 串行 (全局锁)\n"
        f"搜索默认返回: {DEFAULT_COUNT}条"
    )
 
 
if __name__ == "__main__":
    print(
        f"Starting taobao MCP server on 0.0.0.0:{port} "
        f"(sinataoke={SINATAOKE_VERSION}, timeout={CALL_TIMEOUT}s)",
        flush=True,
    )
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
    )
 
