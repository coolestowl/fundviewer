import asyncio
from io import StringIO
import logging
import re
import time
from typing import Any, Dict
from bs4 import BeautifulSoup
import pandas as pd
import httpx
import demjson


async def stock_zh_index_spot_em(symbol: str = "上证系列指数") -> pd.DataFrame:
    """
    东方财富网-行情中心-沪深京指数
    https://quote.eastmoney.com/center/gridlist.html#index_sz
    :param symbol: "上证系列指数"; choice of {"上证系列指数", "深证系列指数", "指数成份", "中证系列指数"}
    :type symbol: str
    :return: 指数的实时行情数据
    :rtype: pandas.DataFrame
    """
    url = "https://48.push2.eastmoney.com/api/qt/clist/get"
    symbol_map = {
        "上证系列指数": "m:1+s:2",
        "深证系列指数": "m:0+t:5",
        "指数成份": "m:1+s:3,m:0+t:5",
        "中证系列指数": "m:2",
    }
    params = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": "f3",
        "fs": symbol_map[symbol],
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152",
        "_": "1704327268532",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    data_json = r.json()
    temp_df = pd.DataFrame(data_json["data"]["diff"])
    temp_df.reset_index(inplace=True)
    temp_df["index"] = temp_df["index"] + 1
    temp_df.rename(
        columns={
            "index": "序号",
            "f2": "最新价",
            "f3": "涨跌幅",
            "f4": "涨跌额",
            "f5": "成交量",
            "f6": "成交额",
            "f7": "振幅",
            "f10": "量比",
            "f12": "代码",
            "f14": "名称",
            "f15": "最高",
            "f16": "最低",
            "f17": "今开",
            "f18": "昨收",
        },
        inplace=True,
    )
    temp_df = temp_df[
        [
            "序号",
            "代码",
            "名称",
            "最新价",
            "涨跌幅",
            "涨跌额",
            "成交量",
            "成交额",
            "振幅",
            "最高",
            "最低",
            "今开",
            "昨收",
            "量比",
        ]
    ]
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"], errors="coerce")
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    temp_df["振幅"] = pd.to_numeric(temp_df["振幅"], errors="coerce")
    temp_df["最高"] = pd.to_numeric(temp_df["最高"], errors="coerce")
    temp_df["最低"] = pd.to_numeric(temp_df["最低"], errors="coerce")
    temp_df["今开"] = pd.to_numeric(temp_df["今开"], errors="coerce")
    temp_df["昨收"] = pd.to_numeric(temp_df["昨收"], errors="coerce")
    temp_df["量比"] = pd.to_numeric(temp_df["量比"], errors="coerce")
    return temp_df


def _replace_comma(x):
    """
    去除单元格中的 ","
    :param x: 单元格元素
    :type x: str
    :return: 处理后的值或原值
    :rtype: str
    """
    if "," in str(x):
        return str(x).replace(",", "")
    else:
        return x


async def get_zh_index_page_count() -> int:
    """
    指数的总页数
    https://vip.stock.finance.sina.com.cn/mkt/#hs_s
    :return: 需要抓取的指数的总页数
    :rtype: int
    """
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCountSimple?node=hs_s"
        )
    page_count = int(re.findall(re.compile(r"\d+"), res.text)[0]) / 80
    if isinstance(page_count, int):
        return page_count
    else:
        return int(page_count) + 1


zh_sina_index_stock_payload = {
    "page": "1",
    "num": "80",
    "sort": "symbol",
    "asc": "1",
    "node": "hs_s",
    "_s_r_a": "page",
}


async def stock_zh_index_spot_sina_page(page: int, sem):
    zh_sina_stock_payload_copy = zh_sina_index_stock_payload.copy()
    zh_sina_stock_payload_copy.update({"page": page})
    async with sem:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeDataSimple",
                params=zh_sina_stock_payload_copy,
            )
    data_json = demjson.decode(res.text)
    return data_json


async def stock_zh_index_spot_sina() -> pd.DataFrame:
    """
    新浪财经-行情中心首页-A股-分类-所有指数
    大量采集会被目标网站服务器封禁 IP, 如果被封禁 IP, 请 10 分钟后再试
    https://vip.stock.finance.sina.com.cn/mkt/#hs_s
    :return: 所有指数的实时行情数据
    :rtype: pandas.DataFrame
    """
    big_df = pd.DataFrame()
    page_count = await get_zh_index_page_count()

    sem = asyncio.Semaphore(6)

    task_list = []
    for page in range(1, page_count + 1):
        task = asyncio.create_task(stock_zh_index_spot_sina_page(page, sem))
        task_list.append(task)
    ret_list = await asyncio.gather(*task_list)

    for data_json in ret_list:
        big_df = pd.concat([big_df, pd.DataFrame(data_json)], ignore_index=True)
    big_df = big_df.map(_replace_comma)
    big_df["trade"] = pd.to_numeric(big_df["trade"], errors="coerce")
    big_df["pricechange"] = pd.to_numeric(big_df["pricechange"], errors="coerce")
    big_df["changepercent"] = pd.to_numeric(big_df["changepercent"], errors="coerce")
    big_df["buy"] = pd.to_numeric(big_df["buy"], errors="coerce")
    big_df["sell"] = pd.to_numeric(big_df["sell"], errors="coerce")
    big_df["settlement"] = pd.to_numeric(big_df["settlement"], errors="coerce")
    big_df["open"] = pd.to_numeric(big_df["open"], errors="coerce")
    big_df["high"] = pd.to_numeric(big_df["high"], errors="coerce")
    big_df["low"] = pd.to_numeric(big_df["low"], errors="coerce")
    big_df.columns = [
        "代码",
        "名称",
        "最新价",
        "涨跌额",
        "涨跌幅",
        "_",
        "_",
        "昨收",
        "今开",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "_",
        "_",
    ]
    big_df = big_df[
        [
            "代码",
            "名称",
            "最新价",
            "涨跌额",
            "涨跌幅",
            "昨收",
            "今开",
            "最高",
            "最低",
            "成交量",
            "成交额",
        ]
    ]
    big_df["最新价"] = pd.to_numeric(big_df["最新价"], errors="coerce")
    big_df["涨跌额"] = pd.to_numeric(big_df["涨跌额"], errors="coerce")
    big_df["涨跌幅"] = pd.to_numeric(big_df["涨跌幅"], errors="coerce")
    big_df["昨收"] = pd.to_numeric(big_df["昨收"], errors="coerce")
    big_df["今开"] = pd.to_numeric(big_df["今开"], errors="coerce")
    big_df["最高"] = pd.to_numeric(big_df["最高"], errors="coerce")
    big_df["最低"] = pd.to_numeric(big_df["最低"], errors="coerce")
    big_df["成交量"] = pd.to_numeric(big_df["成交量"], errors="coerce")
    big_df["成交额"] = pd.to_numeric(big_df["成交额"], errors="coerce")
    return big_df


async def fund_individual_basic_info_xq(
    symbol: str = "000001", timeout: float = 10
) -> pd.DataFrame:
    """
    雪球基金-基金详情
    https://danjuanfunds.com/djapi/fund/675091
    :param symbol: 基金代码
    :type symbol: str
    :param timeout: choice of None or a positive float number
    :type timeout: float
    :return: 基金信息
    :rtype: pandas.DataFrame
    """
    url = f"https://danjuanfunds.com/djapi/fund/{symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers, timeout=timeout)
    json_data: Dict[str, Any] = r.json()["data"]

    ret = {
        "基金代码": json_data.get("fd_code", None),
        "基金名称": json_data.get("fd_name", None),
        "基金全称": json_data.get("fd_full_name", None),
        "基金类型": json_data.get("type_desc", None),
        "成立时间": json_data.get("found_date", None),
        "最新规模": json_data.get("totshare", None),
        "基金公司": json_data.get("keeper_name", None),
        "基金经理": json_data.get("manager_name", None),
        "开放购买": "开放申购" if json_data.get("can_buy", True) else "暂停申购",
        "基金评级": {},
        "历史业绩": {},
    }

    if (
        json_data.get("rating_source") is not None
        and json_data.get("rating_desc") is not None
    ):
        score = json_data.get("rating_desc")
        if "1" in score or "一" in score:
            score_int = 1
        elif "2" in score or "二" in score:
            score_int = 2
        elif "3" in score or "三" in score:
            score_int = 3
        elif "4" in score or "四" in score:
            score_int = 4
        elif "5" in score or "五" in score:
            score_int = 5

        ret["基金评级"] = {json_data["rating_source"]: score_int}

    price_history: Dict[str, Any] = json_data.get("fund_derived", {})
    ret["单位净值"] = float(price_history.get("unit_nav", None))
    ret["更新时间"] = price_history.get("end_date", None)
    ret["历史业绩"]["日增长率"] = float(price_history.get("nav_grtd", None))
    ret["历史业绩"]["月增长率"] = float(price_history.get("nav_grl1m", None))
    ret["历史业绩"]["三月增长率"] = float(price_history.get("nav_grl3m", None))
    ret["历史业绩"]["六月增长率"] = float(price_history.get("nav_grl6m", None))
    ret["历史业绩"]["年增长率"] = float(price_history.get("nav_grl1y", None))
    ret["历史业绩"]["三年增长率"] = float(price_history.get("nav_grl3y", None))

    ret["历史业绩"]["月排名"] = price_history.get("srank_l1m", None)
    ret["历史业绩"]["三月排名"] = price_history.get("srank_l3m", None)
    ret["历史业绩"]["六月排名"] = price_history.get("srank_l6m", None)
    ret["历史业绩"]["年排名"] = price_history.get("srank_l1y", None)
    ret["历史业绩"]["三年排名"] = price_history.get("srank_l3y", None)

    return ret


async def fund_rating_all() -> pd.DataFrame:
    """
    天天基金网-基金评级-基金评级总汇
    https://fund.eastmoney.com/data/fundrating.html
    :return: 基金评级总汇
    :rtype: pandas.DataFrame
    """
    url = "https://fund.eastmoney.com/data/fundrating.html"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
    soup = BeautifulSoup(r.text, "lxml")
    data_text = soup.find("div", attrs={"id": "fundinfo"}).find("script").string
    data_content = [
        item.split("|")
        for item in data_text.split("var")[6]
        .split("=")[1]
        .strip()
        .strip(";")
        .strip('"')
        .strip("|")
        .split("|_")
    ]
    temp_df = pd.DataFrame(data_content)
    temp_df.columns = [
        "代码",
        "简称",
        "类型",
        "基金经理",
        "-",
        "基金公司",
        "-",
        "5星评级家数",
        "-",
        "-",
        "招商证券",
        "-",
        "上海证券",
        "-",
        "-",
        "-",
        "济安金信",
        "-",
        "手续费",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
    ]
    temp_df = temp_df[
        [
            "代码",
            "简称",
            "基金经理",
            "基金公司",
            "5星评级家数",
            "上海证券",
            "招商证券",
            "济安金信",
            "手续费",
            "类型",
        ]
    ]
    temp_df["5星评级家数"] = pd.to_numeric(temp_df["5星评级家数"], errors="coerce")
    temp_df["上海证券"] = pd.to_numeric(temp_df["上海证券"], errors="coerce")
    temp_df["招商证券"] = pd.to_numeric(temp_df["招商证券"], errors="coerce")
    temp_df["济安金信"] = pd.to_numeric(temp_df["济安金信"], errors="coerce")
    temp_df["手续费"] = (
        pd.to_numeric(temp_df["手续费"].str.strip("%"), errors="coerce") / 100
    )
    return temp_df


async def fund_portfolio_hold_em(
    symbol: str = "000001", date: str = "2023"
) -> pd.DataFrame:
    """
    天天基金网-基金档案-投资组合-基金持仓
    https://fundf10.eastmoney.com/ccmx_000001.html
    :param symbol: 基金代码
    :type symbol: str
    :param date: 查询年份
    :type date: str
    :return: 基金持仓
    :rtype: pandas.DataFrame
    """
    url = "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "jjcc",
        "code": symbol,
        "topline": "30",
        "year": date,
        "month": "",
        "rt": "0.913877030254846",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    data_text = r.text
    data_json = demjson.decode(data_text[data_text.find("{") : -1])
    soup = BeautifulSoup(data_json["content"], "lxml")
    item_label = [
        item.text.split("\xa0\xa0")[1]
        for item in soup.find_all("h4", attrs={"class": "t"})
    ]
    big_df = pd.DataFrame()
    for item in range(len(item_label)):
        temp_df = pd.read_html(
            StringIO(data_json["content"]), converters={"股票代码": str}
        )[item]
        del temp_df["相关资讯"]
        temp_df.rename(columns={"占净值 比例": "占净值比例"}, inplace=True)
        temp_df["占净值比例"] = (
            temp_df["占净值比例"].str.split("%", expand=True).iloc[:, 0]
        )
        temp_df.rename(
            columns={"持股数（万股）": "持股数", "持仓市值（万元）": "持仓市值"},
            inplace=True,
        )
        temp_df.rename(
            columns={"持股数 （万股）": "持股数", "持仓市值 （万元）": "持仓市值"},
            inplace=True,
        )
        temp_df.rename(
            columns={"持股数（万股）": "持股数", "持仓市值（万元人民币）": "持仓市值"},
            inplace=True,
        )
        temp_df.rename(
            columns={
                "持股数 （万股）": "持股数",
                "持仓市值 （万元人民币）": "持仓市值",
            },
            inplace=True,
        )

        temp_df["季度"] = item_label[item]
        temp_df = temp_df[
            [
                "序号",
                "股票代码",
                "股票名称",
                "占净值比例",
                "持股数",
                "持仓市值",
                "季度",
            ]
        ]
        big_df = pd.concat([big_df, temp_df], ignore_index=True)
    if len(big_df) == 0:
        return big_df
    big_df["占净值比例"] = pd.to_numeric(big_df["占净值比例"], errors="coerce")
    big_df["持股数"] = pd.to_numeric(big_df["持股数"], errors="coerce")
    big_df["持仓市值"] = pd.to_numeric(big_df["持仓市值"], errors="coerce")
    big_df["序号"] = range(1, len(big_df) + 1)
    return big_df


async def fund_portfolio_bond_hold_em(
    symbol: str = "000001", date: str = "2021"
) -> pd.DataFrame:
    """
    天天基金网-基金档案-投资组合-债券持仓
    http://fundf10.eastmoney.com/ccmx1_000001.html
    :param symbol: 基金代码
    :type symbol: str
    :param date: 查询年份
    :type date: str
    :return: 债券持仓
    :rtype: pandas.DataFrame
    """
    url = "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "zqcc",
        "code": symbol,
        "year": date,
        "rt": "0.913877030254846",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    data_text = r.text
    data_json = demjson.decode(data_text[data_text.find("{") : -1])
    soup = BeautifulSoup(data_json["content"], "lxml")
    item_label = [
        item.text.split("\xa0\xa0")[1]
        for item in soup.find_all("h4", attrs={"class": "t"})
    ]
    big_df = pd.DataFrame()
    for item in range(len(item_label)):
        temp_df = pd.read_html(data_json["content"], converters={"债券代码": str})[item]
        temp_df["占净值比例"] = (
            temp_df["占净值比例"].str.split("%", expand=True).iloc[:, 0]
        )
        temp_df.rename(columns={"持仓市值（万元）": "持仓市值"}, inplace=True)
        temp_df["季度"] = item_label[item]
        temp_df = temp_df[
            [
                "序号",
                "债券代码",
                "债券名称",
                "占净值比例",
                "持仓市值",
                "季度",
            ]
        ]
        big_df = pd.concat([big_df, temp_df], ignore_index=True)
    if len(big_df) == 0:
        return big_df
    big_df["占净值比例"] = pd.to_numeric(big_df["占净值比例"], errors="coerce")
    big_df["持仓市值"] = pd.to_numeric(big_df["持仓市值"], errors="coerce")
    big_df["序号"] = range(1, len(big_df) + 1)
    return big_df


async def get_fund_share(code: str):
    header = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.183"
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://fundf10.eastmoney.com/zcpz_{code}.html", headers=header
            )
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.find("table", attrs={"class": "w782 comm tzxq"})

        tbody = table.find("tbody")
        tr = tbody.find("tr")
        td_list = tr.find_all("td")
        logging.debug(td_list)
        try:
            stock_share = float(td_list[1].text.replace("%", "").replace("-", ""))
        except Exception:
            stock_share = 0
        try:
            bond_share = float(td_list[2].text.replace("%", "").replace("-", ""))
        except Exception:
            bond_share = 0

        other_share = 1 - stock_share - bond_share

        try:
            total_scale = float(td_list[-1].text)
        except Exception:
            total_scale = 0

        return {
            "stock_share": stock_share,
            "bond_share": bond_share,
            "other_share": other_share,
            "total_scale": total_scale,
        }
    except Exception as e:
        logging.error(f"get fund scale error: {e}")
        return None


async def stock_zh_a_spot_em() -> pd.DataFrame:
    """
    东方财富网-沪深京 A 股-实时行情
    https://quote.eastmoney.com/center/gridlist.html#hs_a_board
    :return: 实时行情
    :rtype: pandas.DataFrame
    """
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "50000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
        "_": "1623833739532",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    data_json = r.json()
    if not data_json["data"]["diff"]:
        return pd.DataFrame()
    temp_df = pd.DataFrame(data_json["data"]["diff"])
    temp_df.columns = [
        "_",
        "最新价",
        "涨跌幅",
        "涨跌额",
        "成交量",
        "成交额",
        "振幅",
        "换手率",
        "市盈率-动态",
        "量比",
        "5分钟涨跌",
        "代码",
        "_",
        "名称",
        "最高",
        "最低",
        "今开",
        "昨收",
        "总市值",
        "流通市值",
        "涨速",
        "市净率",
        "60日涨跌幅",
        "年初至今涨跌幅",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
    ]
    temp_df.reset_index(inplace=True)
    temp_df["index"] = temp_df.index + 1
    temp_df.rename(columns={"index": "序号"}, inplace=True)
    temp_df = temp_df[
        [
            "序号",
            "代码",
            "名称",
            "最新价",
            "涨跌幅",
            "涨跌额",
            "成交量",
            "成交额",
            "振幅",
            "最高",
            "最低",
            "今开",
            "昨收",
            "量比",
            "换手率",
            "市盈率-动态",
            "市净率",
            "总市值",
            "流通市值",
            "涨速",
            "5分钟涨跌",
            "60日涨跌幅",
            "年初至今涨跌幅",
        ]
    ]
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"], errors="coerce")
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    temp_df["振幅"] = pd.to_numeric(temp_df["振幅"], errors="coerce")
    temp_df["最高"] = pd.to_numeric(temp_df["最高"], errors="coerce")
    temp_df["最低"] = pd.to_numeric(temp_df["最低"], errors="coerce")
    temp_df["今开"] = pd.to_numeric(temp_df["今开"], errors="coerce")
    temp_df["昨收"] = pd.to_numeric(temp_df["昨收"], errors="coerce")
    temp_df["量比"] = pd.to_numeric(temp_df["量比"], errors="coerce")
    temp_df["换手率"] = pd.to_numeric(temp_df["换手率"], errors="coerce")
    temp_df["市盈率-动态"] = pd.to_numeric(temp_df["市盈率-动态"], errors="coerce")
    temp_df["市净率"] = pd.to_numeric(temp_df["市净率"], errors="coerce")
    temp_df["总市值"] = pd.to_numeric(temp_df["总市值"], errors="coerce")
    temp_df["流通市值"] = pd.to_numeric(temp_df["流通市值"], errors="coerce")
    temp_df["涨速"] = pd.to_numeric(temp_df["涨速"], errors="coerce")
    temp_df["5分钟涨跌"] = pd.to_numeric(temp_df["5分钟涨跌"], errors="coerce")
    temp_df["60日涨跌幅"] = pd.to_numeric(temp_df["60日涨跌幅"], errors="coerce")
    temp_df["年初至今涨跌幅"] = pd.to_numeric(
        temp_df["年初至今涨跌幅"], errors="coerce"
    )
    return temp_df


async def stock_hk_spot_em() -> pd.DataFrame:
    """
    东方财富网-港股-实时行情
    https://quote.eastmoney.com/center/gridlist.html#hk_stocks
    :return: 港股-实时行情
    :rtype: pandas.DataFrame
    """
    url = "https://72.push2.eastmoney.com/api/qt/clist/get"
    ts = time.time()
    tss = int(ts * 1000)
    params = {
        "pn": "1",
        "pz": "50000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
        "_": f"{tss}",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    data_json = r.json()
    temp_df = pd.DataFrame(data_json["data"]["diff"])
    temp_df.columns = [
        "_",
        "最新价",
        "涨跌幅",
        "涨跌额",
        "成交量",
        "成交额",
        "振幅",
        "换手率",
        "市盈率-动态",
        "量比",
        "_",
        "代码",
        "_",
        "名称",
        "最高",
        "最低",
        "今开",
        "昨收",
        "_",
        "_",
        "_",
        "市净率",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
    ]
    temp_df.reset_index(inplace=True)
    temp_df["index"] = temp_df.index + 1
    temp_df.rename(columns={"index": "序号"}, inplace=True)
    temp_df = temp_df[
        [
            "序号",
            "代码",
            "名称",
            "最新价",
            "涨跌额",
            "涨跌幅",
            "今开",
            "最高",
            "最低",
            "昨收",
            "成交量",
            "成交额",
        ]
    ]
    temp_df["序号"] = pd.to_numeric(temp_df["序号"], errors="coerce")
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce")
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["今开"] = pd.to_numeric(temp_df["今开"], errors="coerce")
    temp_df["最高"] = pd.to_numeric(temp_df["最高"], errors="coerce")
    temp_df["最低"] = pd.to_numeric(temp_df["最低"], errors="coerce")
    temp_df["昨收"] = pd.to_numeric(temp_df["昨收"], errors="coerce")
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    return temp_df


async def stock_us_spot_em() -> pd.DataFrame:
    """
    东方财富网-美股-实时行情
    https://quote.eastmoney.com/center/gridlist.html#us_stocks
    :return: 美股-实时行情; 延迟 15 min
    :rtype: pandas.DataFrame
    """
    url = "https://72.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "20000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:105,m:106,m:107",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,"
        "f21,f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152",
        "_": "1624010056945",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    data_json = r.json()
    temp_df = pd.DataFrame(data_json["data"]["diff"])
    temp_df.columns = [
        "_",
        "最新价",
        "涨跌幅",
        "涨跌额",
        "成交量",
        "成交额",
        "振幅",
        "换手率",
        "_",
        "_",
        "_",
        "简称",
        "编码",
        "名称",
        "最高价",
        "最低价",
        "开盘价",
        "昨收价",
        "总市值",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
        "_",
        "市盈率",
        "_",
        "_",
        "_",
        "_",
        "_",
    ]
    temp_df.reset_index(inplace=True)
    temp_df["index"] = range(1, len(temp_df) + 1)
    temp_df.rename(columns={"index": "序号"}, inplace=True)
    temp_df["代码"] = temp_df["编码"].astype(str) + "." + temp_df["简称"]
    temp_df = temp_df[
        [
            "序号",
            "名称",
            "最新价",
            "涨跌额",
            "涨跌幅",
            "开盘价",
            "最高价",
            "最低价",
            "昨收价",
            "总市值",
            "市盈率",
            "成交量",
            "成交额",
            "振幅",
            "换手率",
            "代码",
        ]
    ]
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce")
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["开盘价"] = pd.to_numeric(temp_df["开盘价"], errors="coerce")
    temp_df["最高价"] = pd.to_numeric(temp_df["最高价"], errors="coerce")
    temp_df["最低价"] = pd.to_numeric(temp_df["最低价"], errors="coerce")
    temp_df["昨收价"] = pd.to_numeric(temp_df["昨收价"], errors="coerce")
    temp_df["总市值"] = pd.to_numeric(temp_df["总市值"], errors="coerce")
    temp_df["市盈率"] = pd.to_numeric(temp_df["市盈率"], errors="coerce")
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    temp_df["振幅"] = pd.to_numeric(temp_df["振幅"], errors="coerce")
    temp_df["换手率"] = pd.to_numeric(temp_df["换手率"], errors="coerce")
    return temp_df


async def bond_new_composite_index_cbond(
    indicator: str = "财富", period: str = "总值"
) -> pd.DataFrame:
    """
    中国债券信息网-中债指数-中债指数族系-总指数-综合类指数-中债-新综合指数
    https://yield.chinabond.com.cn/cbweb-mn/indices/single_index_query
    :param indicator: choice of {"全价", "净价", "财富", "平均市值法久期", "平均现金流法久期", "平均市值法凸性", "平均现金流法凸性", "平均现金流法到期收益率", "平均市值法到期收益率", "平均基点价值", "平均待偿期", "平均派息率", "指数上日总市值", "财富指数涨跌幅", "全价指数涨跌幅", "净价指数涨跌幅", "现券结算量"}
    :type indicator: str
    :param period: choice of {"总值", "1年以下", "1-3年", "3-5年", "5-7年", "7-10年", "10年以上", "0-3个月", "3-6个月", "6-9个月", "9-12个月", "0-6个月", "6-12个月"}
    :type period: str
    :return: 新综合指数
    :rtype: pandas.DataFrame
    """
    indicator_map = {
        "全价": "QJZS",
        "净价": "JJZS",
        "财富": "CFZS",
        "平均市值法久期": "PJSZFJQ",
        "平均现金流法久期": "PJXJLFJQ",
        "平均市值法凸性": "PJSZFTX",
        "平均现金流法凸性": "PJXJLFTX",
        "平均现金流法到期收益率": "PJDQSYL",
        "平均市值法到期收益率": "PJSZFDQSYL",
        "平均基点价值": "PJJDJZ",
        "平均待偿期": "PJDCQ",
        "平均派息率": "PJPXL",
        "指数上日总市值": "ZSZSZ",
        "财富指数涨跌幅": "CFZSZDF",
        "全价指数涨跌幅": "QJZSZDF",
        "净价指数涨跌幅": "JJZSZDF",
        "现券结算量": "XQJSL",
    }
    period_map = {
        "总值": "00",
        "1年以下": "01",
        "1-3年": "02",
        "3-5年": "03",
        "5-7年": "04",
        "7-10年": "05",
        "10年以上": "06",
        "0-3个月": "07",
        "3-6个月": "08",
        "6-9个月": "09",
        "9-12个月": "10",
        "0-6个月": "11",
        "6-12个月": "12",
    }
    url = "https://yield.chinabond.com.cn/cbweb-mn/indices/singleIndexQuery"
    params = {
        "indexid": "8a8b2ca0332abed20134ea76d8885831",
        "": "",
        "qxlxt": period_map[period],
        "": "",
        "ltcslx": "",
        "": "",
        "zslxt": indicator_map[indicator],
        "": "",
        "zslxt": indicator_map[indicator],
        "": "",
        "lx": "1",
        "": "",
        "locale": "",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, params=params)
    data_json = r.json()
    temp_df = pd.DataFrame.from_dict(
        data_json[f"{indicator_map[indicator]}_{period_map[period]}"],
        orient="index",
    )
    temp_df.reset_index(inplace=True)
    temp_df.columns = ["date", "value"]
    temp_df["date"] = temp_df["date"].astype(float)
    temp_df["date"] = (
        pd.to_datetime(temp_df["date"], unit="ms", errors="coerce", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.date
    )
    temp_df["value"] = pd.to_numeric(temp_df["value"], errors="coerce")
    return temp_df


async def bond_cb_index_jsl() -> pd.DataFrame:
    """
    首页-可转债-集思录可转债等权指数
    https://www.jisilu.cn/web/data/cb/index
    :return: 集思录可转债等权指数
    :rtype: pandas.DataFrame
    """
    url = "https://www.jisilu.cn/webapi/cb/index_history/"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
    data_dict = demjson.decode(r.text)["data"]
    temp_df = pd.DataFrame(data_dict)
    return temp_df


async def bond_cb_jsl(cookie: str = None) -> pd.DataFrame:
    """
    集思录可转债
    https://app.jisilu.cn/data/cbnew/#cb
    :param cookie: 输入获取到的游览器 cookie
    :type cookie: str
    :return: 集思录可转债
    :rtype: pandas.DataFrame
    """
    url = "https://app.jisilu.cn/data/cbnew/cb_list_new/"
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "cookie": cookie,
        "origin": "https://app.jisilu.cn",
        "pragma": "no-cache",
        "referer": "https://app.jisilu.cn/data/cbnew/",
        "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.164 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    params = {
        "___jsl": "LST___t=1627021692978",
    }
    payload = {
        "fprice": "",
        "tprice": "",
        "curr_iss_amt": "",
        "volume": "",
        "svolume": "",
        "premium_rt": "",
        "ytm_rt": "",
        "market": "",
        "rating_cd": "",
        "is_search": "N",
        "market_cd[]": "shmb",  # noqa: F601
        "market_cd[]": "shkc",  # noqa: F601
        "market_cd[]": "szmb",  # noqa: F601
        "market_cd[]": "szcy",  # noqa: F601
        "btype": "",
        "listed": "Y",
        "qflag": "N",
        "sw_cd": "",
        "bond_ids": "",
        "rp": "50",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, params=params, json=payload, headers=headers)
    data_json = r.json()
    temp_df = pd.DataFrame([item["cell"] for item in data_json["rows"]])
    temp_df.rename(
        columns={
            "bond_id": "代码",
            "bond_nm": "转债名称",
            "price": "现价",
            "increase_rt": "涨跌幅",
            "stock_id": "正股代码",
            "stock_nm": "正股名称",
            "sprice": "正股价",
            "sincrease_rt": "正股涨跌",
            "pb": "正股PB",
            "convert_price": "转股价",
            "convert_value": "转股价值",
            "premium_rt": "转股溢价率",
            "dblow": "双低",
            "rating_cd": "债券评级",
            "put_convert_price": "回售触发价",
            "force_redeem_price": "强赎触发价",
            "convert_amt_ratio": "转债占比",
            "maturity_dt": "到期时间",
            "year_left": "剩余年限",
            "curr_iss_amt": "剩余规模",
            "volume": "成交额",
            "turnover_rt": "换手率",
            "ytm_rt": "到期税前收益",
        },
        inplace=True,
    )

    temp_df = temp_df[
        [
            "代码",
            "转债名称",
            "现价",
            "涨跌幅",
            "正股代码",
            "正股名称",
            "正股价",
            "正股涨跌",
            "正股PB",
            "转股价",
            "转股价值",
            "转股溢价率",
            "债券评级",
            "回售触发价",
            "强赎触发价",
            "转债占比",
            "到期时间",
            "剩余年限",
            "剩余规模",
            "成交额",
            "换手率",
            "到期税前收益",
            "双低",
        ]
    ]
    temp_df["到期时间"] = pd.to_datetime(temp_df["到期时间"]).dt.date
    temp_df["现价"] = pd.to_numeric(temp_df["现价"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["正股价"] = pd.to_numeric(temp_df["正股价"], errors="coerce")
    temp_df["正股涨跌"] = pd.to_numeric(temp_df["正股涨跌"], errors="coerce")
    temp_df["正股PB"] = pd.to_numeric(temp_df["正股PB"], errors="coerce")
    temp_df["转股价"] = pd.to_numeric(temp_df["转股价"], errors="coerce")
    temp_df["转股价值"] = pd.to_numeric(temp_df["转股价值"], errors="coerce")
    temp_df["转股溢价率"] = pd.to_numeric(temp_df["转股溢价率"], errors="coerce")
    temp_df["回售触发价"] = pd.to_numeric(temp_df["回售触发价"], errors="coerce")
    temp_df["强赎触发价"] = pd.to_numeric(temp_df["强赎触发价"], errors="coerce")
    temp_df["转债占比"] = pd.to_numeric(temp_df["转债占比"], errors="coerce")
    temp_df["剩余年限"] = pd.to_numeric(temp_df["剩余年限"], errors="coerce")
    temp_df["剩余规模"] = pd.to_numeric(temp_df["剩余规模"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    temp_df["换手率"] = pd.to_numeric(temp_df["换手率"], errors="coerce")
    temp_df["到期税前收益"] = pd.to_numeric(temp_df["到期税前收益"], errors="coerce")
    return temp_df


async def bond_cov_comparison() -> pd.DataFrame:
    """
    东方财富网-行情中心-债券市场-可转债比价表
    https://quote.eastmoney.com/center/fullscreenlist.html#convertible_comparison
    :return: 可转债比价表数据
    :rtype: pandas.DataFrame
    """
    url = "https://16.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f243",
        "fs": "b:MK0354",
        "fields": "f1,f152,f2,f3,f12,f13,f14,f227,f228,f229,f230,f231,f232,f233,f234,"
        "f235,f236,f237,f238,f239,f240,f241,f242,f26,f243",
        "_": "1590386857527",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    text_data = r.text
    json_data = demjson.decode(text_data)
    temp_df = pd.DataFrame(json_data["data"]["diff"])
    temp_df.reset_index(inplace=True)
    temp_df["index"] = range(1, len(temp_df) + 1)
    temp_df.columns = [
        "序号",
        "_",
        "转债最新价",
        "转债涨跌幅",
        "转债代码",
        "_",
        "转债名称",
        "上市日期",
        "_",
        "纯债价值",
        "_",
        "正股最新价",
        "正股涨跌幅",
        "_",
        "正股代码",
        "_",
        "正股名称",
        "转股价",
        "转股价值",
        "转股溢价率",
        "纯债溢价率",
        "回售触发价",
        "强赎触发价",
        "到期赎回价",
        "开始转股日",
        "申购日期",
    ]
    temp_df = temp_df[
        [
            "序号",
            "转债代码",
            "转债名称",
            "转债最新价",
            "转债涨跌幅",
            "正股代码",
            "正股名称",
            "正股最新价",
            "正股涨跌幅",
            "转股价",
            "转股价值",
            "转股溢价率",
            "纯债溢价率",
            "回售触发价",
            "强赎触发价",
            "到期赎回价",
            "纯债价值",
            "开始转股日",
            "上市日期",
            "申购日期",
        ]
    ]
    return temp_df


async def fund_open_fund_daily_em() -> pd.DataFrame:
    """
    东方财富网-天天基金网-基金数据-开放式基金净值
    https://fund.eastmoney.com/fund.html#os_0;isall_0;ft_;pt_1
    :return: 当前交易日的所有开放式基金净值数据
    :rtype: pandas.DataFrame
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"
    }
    url = "http://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
    params = {
        "t": "1",
        "lx": "1",
        "letter": "",
        "gsid": "",
        "text": "",
        "sort": "zdf,desc",
        "page": "1,20000",
        "dt": "1580914040623",
        "atfc": "",
        "onlySale": "0",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(url, params=params, headers=headers)
    text_data = res.text
    data_json = demjson.decode(text_data.strip("var db="))
    temp_df = pd.DataFrame(data_json["datas"])
    show_day = data_json["showday"]
    temp_df.columns = [
        "基金代码",
        "基金简称",
        "-",
        f"{show_day[0]}-单位净值",
        f"{show_day[0]}-累计净值",
        f"{show_day[1]}-单位净值",
        f"{show_day[1]}-累计净值",
        "日增长值",
        "日增长率",
        "申购状态",
        "赎回状态",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "手续费",
        "-",
        "-",
        "-",
    ]
    data_df = temp_df[
        [
            "基金代码",
            "基金简称",
            f"{show_day[0]}-单位净值",
            f"{show_day[0]}-累计净值",
            f"{show_day[1]}-单位净值",
            f"{show_day[1]}-累计净值",
            "日增长值",
            "日增长率",
            "申购状态",
            "赎回状态",
            "手续费",
        ]
    ]
    return data_df
