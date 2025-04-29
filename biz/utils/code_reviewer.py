import abc
import os
import re
from typing import Dict, Any, List

import yaml
from jinja2 import Template
import requests
import json

from biz.llm.factory import Factory
from biz.utils.log import logger
from biz.utils.token_util import count_tokens, truncate_text_by_tokens


class BaseReviewer(abc.ABC):
    """代码审查基类"""

    def __init__(self, prompt_key: str):
        self.client = Factory().getClient()
        self.prompts = self._load_prompts(
            prompt_key, os.getenv("REVIEW_STYLE", "professional")
        )

    def _load_prompts(self, prompt_key: str, style="professional") -> Dict[str, Any]:
        """加载提示词配置"""
        prompt_templates_file = "conf/prompt_templates.yml"
        try:
            # 在打开 YAML 文件时显式指定编码为 UTF-8，避免使用系统默认的 GBK 编码。
            with open(prompt_templates_file, "r", encoding="utf-8") as file:
                prompts = yaml.safe_load(file).get(prompt_key, {})

                # 使用Jinja2渲染模板
                def render_template(template_str: str) -> str:
                    return Template(template_str).render(style=style)

                system_prompt = render_template(prompts["system_prompt"])
                user_prompt = render_template(prompts["user_prompt"])

                return {
                    "system_message": {"role": "system", "content": system_prompt},
                    "user_message": {"role": "user", "content": user_prompt},
                }
        except (FileNotFoundError, KeyError, yaml.YAMLError) as e:
            logger.error(f"加载提示词配置失败: {e}")
            raise Exception(f"提示词配置加载失败: {e}")

    def call_llm(self, messages: List[Dict[str, Any]]) -> str:
        """调用 LLM 进行代码审核"""
        logger.info(f"向 AI 发送代码 Review 请求, messages: {messages}")
        review_result = self.client.completions(messages=messages)
        logger.info(f"收到 AI 返回结果: {review_result}")
        return review_result

    @abc.abstractmethod
    def review_code(self, *args, **kwargs) -> str:
        """抽象方法，子类必须实现"""
        pass


class CodeReviewer(BaseReviewer):
    """代码 Diff 级别的审查"""

    def __init__(self):
        super().__init__("code_review_prompt")

    def review_and_strip_code(self, changes_text: str, commits_text: str = "") -> str:
        """
        Review判断changes_text超出取前REVIEW_MAX_TOKENS个token，超出则截断changes_text，
        调用review_code方法，返回review_result，如果review_result是markdown格式，则去掉头尾的```
        :param changes_text:
        :param commits_text:
        :return:
        """
        # 如果超长，取前REVIEW_MAX_TOKENS个token
        review_max_tokens = int(os.getenv("REVIEW_MAX_TOKENS", 10000))
        # 如果changes为空,打印日志
        if not changes_text:
            logger.info("代码为空, diffs_text = %", str(changes_text))
            return "代码为空"

        # 计算tokens数量，如果超过REVIEW_MAX_TOKENS，截断changes_text
        tokens_count = count_tokens(changes_text)
        if tokens_count > review_max_tokens:
            changes_text = truncate_text_by_tokens(changes_text, review_max_tokens)

        review_result = self.review_code(changes_text, commits_text).strip()
        if review_result.startswith("```markdown") and review_result.endswith("```"):
            return review_result[11:-3].strip()
        return review_result

    def review_code(self, changes_text: str, commits_text: str = "") -> str:
        """Review 代码并返回结果"""
        try:
            # 从提交信息中提取关键词用于知识库查询
            query_keywords = self._extract_keywords_from_commits(commits_text)

            # 查询知识库
            knowledge_base = self._query_knowledge_base(query_keywords)

            # 调用 review_code 方法进行代码评审
            review_result = self.call_llm(
                [
                    self.prompts["system_message"],
                    {
                        "role": "user",
                        "content": self.prompts["user_message"]["content"].format(
                            diffs_text=changes_text,
                            commits_text=commits_text,
                            knowledge_base=knowledge_base,
                        ),
                    },
                ]
            ).strip()

            return review_result
        except Exception as e:
            logger.error(f"代码评审失败: {e}")
            return f"代码评审失败: {str(e)}"

    def _extract_keywords_from_commits(self, commits_text: str) -> str:
        """从提交信息中提取关键词"""

        # todo 通过(commits、 函数名、注释信息) 提取影响范围的核心关键字, 然后再检索知识库
        return commits_text

    def _query_knowledge_base(self, query: str) -> str:
        """查询知识库"""
        try:
            if not query:
                return ""

            knowledge_base_url = os.getenv("KNOWLEDGE_BASE_URL")
            if not knowledge_base_url:
                logger.warning("未配置知识库URL环境变量(KNOWLEDGE_BASE_URL)，将跳过知识库查询")
                return ""
            response = requests.post(
                f"{knowledge_base_url}/api/document/search",
                json={"q": query, "size": 2},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(f"知识库查询失败: {response.status_code}")
                return ""

            result = response.json()
            if not result.get("success"):
                logger.error(f"知识库查询失败: {result.get('message')}")
                return ""

            # 提取并格式化知识库内容
            knowledge_items = []
            for item in result["data"]["items"]:
                title = item["title"]
                segments = item["segments"]
                knowledge_items.extend([f"{title}: {segment}" for segment in segments])

            return "\n".join(knowledge_items)

        except Exception as e:
            logger.error(f"知识库查询失败: {e}")
            return ""

    @staticmethod
    def parse_review_score(review_text: str) -> int:
        """解析 AI 返回的 Review 结果，返回评分"""
        if not review_text:
            return 0
        match = re.search(r"总分[:：]\s*(\d+)分?", review_text)
        return int(match.group(1)) if match else 0
