import atexit
import json
import os
import traceback
from datetime import datetime
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, send_from_directory

from biz.gitlab.webhook_handler import slugify_url
from biz.queue.worker import handle_merge_request_event, handle_push_event, handle_github_pull_request_event, handle_github_push_event
from biz.service.review_service import ReviewService
from biz.utils.im import notifier
from biz.utils.log import logger
from biz.utils.queue import handle_queue
from biz.utils.reporter import Reporter

from biz.utils.config_checker import check_config
from sqlalchemy import text
load_dotenv("conf/.env")
api_app = Flask(__name__)

# 添加静态文件夹配置，用于存放CSS、JS等资源
api_app.static_folder = 'static'


push_review_enabled = os.environ.get('PUSH_REVIEW_ENABLED', '0') == '1'


@api_app.route('/')
def home():
    return """<h2>The code review api server is running.</h2>
              <p>GitHub project address: <a href="https://github.com/sunmh207/AI-Codereview-Gitlab" target="_blank">
              https://github.com/sunmh207/AI-Codereview-Gitlab</a></p>
              <p>Gitee project address: <a href="https://gitee.com/sunminghui/ai-codereview-gitlab" target="_blank">https://gitee.com/sunminghui/ai-codereview-gitlab</a></p>
              <p>Push Review Page: <a href="/review/push_logs" target="_blank">Push Review Logs</a></p>
              """

# 添加获取push_review_log列表数据的API端点
@api_app.route('/api/review/push_logs', methods=['GET'])
def get_push_logs_api():
    try:
        # 获取查询参数
        authors = request.args.getlist('authors')
        project_names = request.args.getlist('project_names')
        
        # 获取日期范围
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        start_timestamp = None
        end_timestamp = None
        
        if start_date:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
            start_timestamp = int(start_datetime.timestamp())
        
        if end_date:
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59)
            end_timestamp = int(end_datetime.timestamp())
        
        # 获取数据
        df = ReviewService().get_push_review_logs(
            authors=authors if authors else None,
            project_names=project_names if project_names else None,
            updated_at_gte=start_timestamp,
            updated_at_lte=end_timestamp
        )
        
        if df.empty:
            return jsonify([])
            
        # 转换数据为JSON格式
        result = df.to_dict(orient='records')
        
        # 返回数据
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取Push Review日志数据失败: {e}")
        return jsonify({"error": str(e)}), 500

# 添加一个新的API端点，用于获取具体的评审结果
@api_app.route('/api/review/push_result/<int:review_id>', methods=['GET'])
def get_push_review_result(review_id):
    try:
        # 获取评审结果
        result = ReviewService().get_push_review_result_by_id(review_id)
        if not result:
            return jsonify({"error": "找不到该评审记录"}), 404
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取评审结果失败: {e}")
        return jsonify({"error": str(e)}), 500

# 添加一个新的API端点，用于展示具体的评审结果页面
@api_app.route('/review/push_result/<int:review_id>')
def push_review_result_page(review_id):
    # 使用简单的HTML页面展示评审结果
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>代码评审结果</title>
        <link rel="stylesheet" href="/static/css/bootstrap.min.css">
        <script src="/static/js/jquery.min.js"></script>
        <script src="/static/js/bootstrap.bundle.min.js"></script>
        <script src="/static/js/marked.min.js"></script>
        <style>
            pre {
                background-color: #f8f9fa;
                padding: 1rem;
                border-radius: 5px;
                overflow-x: auto;
            }
            code {
                font-family: Monaco, Consolas, "Andale Mono", "DejaVu Sans Mono", monospace;
            }
            .review-header {
                margin-bottom: 2rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid #dee2e6;
            }
            .review-score {
                font-size: 3rem;
                font-weight: bold;
            }
            .score-container {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 1rem;
                background-color: #f8f9fa;
                border-radius: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container my-4">
            <div class="review-header">
                <div class="row">
                    <div class="col-md-9">
                        <h2 id="project-name"></h2>
                        <p>作者: <span id="author"></span> | 更新时间: <span id="updated-at"></span></p>
                        <p>提交信息: <span id="commit-messages"></span></p>
                    </div>
                    <div class="col-md-3">
                        <div class="score-container">
                            <div class="review-score" id="score"></div>
                            <div>评分</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card mb-4">
                <div class="card-header">
                    <h3 class="mb-0">评审结果</h3>
                </div>
                <div class="card-body">
                    <div id="review-result"></div>
                </div>
            </div>
            
            <div class="text-center">
                <a href="/review/push_logs" class="btn btn-primary">返回列表</a>
            </div>
        </div>
        
        <script>
            // 获取URL参数中的review_id
            const reviewId = window.location.pathname.split('/').pop();
            
            // 获取评审结果
            fetch(`/api/review/push_result/${reviewId}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('获取评审结果失败');
                    }
                    return response.json();
                })
                .then(data => {
                    // 填充基本信息
                    document.getElementById('project-name').textContent = data.project_name;
                    document.getElementById('author').textContent = data.author;
                    document.getElementById('updated-at').textContent = data.updated_at_format || data.updated_at;
                    document.getElementById('commit-messages').textContent = data.commit_messages;
                    document.getElementById('score').textContent = data.score;
                    
                    // 渲染评审结果（Markdown格式）
                    const reviewResult = data.review_result;
                    if (reviewResult) {
                        document.getElementById('review-result').innerHTML = marked.parse(reviewResult);
                    } else {
                        document.getElementById('review-result').innerHTML = '<div class="alert alert-info">无评审结果</div>';
                    }
                })
                .catch(error => {
                    console.error('获取评审结果失败:', error);
                    document.getElementById('review-result').innerHTML = 
                        `<div class="alert alert-danger">获取评审结果失败: ${error.message}</div>`;
                });
        </script>
    </body>
    </html>
    """
    return html_content

# 添加用于展示push_review_log的HTML页面
@api_app.route('/review/push_logs')
def push_logs_page():
    # 使用简单的HTML页面展示数据
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Push Review 日志</title>
        <link rel="stylesheet" href="/static/css/bootstrap.min.css">
        <script src="/static/js/jquery.min.js"></script>
        <script src="/static/js/bootstrap.bundle.min.js"></script>
        <script src="/static/js/echarts.min.js"></script>
        <style>
            .chart-container {
                height: 300px;
                margin-bottom: 20px;
            }
            .filter-section {
                margin-bottom: 20px;
                padding: 15px;
                background-color: #f8f9fa;
                border-radius: 5px;
            }
            /* 添加表格列宽控制 */
            .table th, .table td {
                white-space: nowrap;
            }
            .table .project-column {
                width: 15%;
            }
            .table .author-column {
                width: 10%;
            }
            .table .time-column {
                width: 15%;
            }
            .table .message-column {
                width: 40%;
                max-width: 300px;
                white-space: normal;
                word-break: break-word;
            }
            .table .score-column {
                width: 10%;
                text-align: center;
            }
            .table .action-column {
                width: 10%;
                text-align: center;
            }
            /* 改进进度条样式 */
            .score-progress {
                height: 25px;
                border-radius: 10px;
                background-color: #f0f0f0;
                overflow: hidden;
                box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);
            }
            .score-progress .progress-bar {
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-weight: 600;
                transition: width 0.6s ease;
                background-image: linear-gradient(to right, #4da6ff, #0066cc);
            }
            /* 改进按钮样式 */
            .review-btn {
                display: inline-block;
                padding: 1px 8px;
                background-color: #8b8f93;
                color: white;
                border-radius: 4px;
                text-decoration: none;
                transition: all 0.3s ease;
                border: none;
                font-weight: 500;
            }
            .review-btn:hover {
                background-color: #e8ecf1;
               
            }
        </style>
    </head>
    <body>
        <div class="container my-4">
            <h2 class="mb-4 text-center">Push Review 日志</h2>
            
            <div class="filter-section">
                <div class="row">
                    <div class="col-md-3 mb-3">
                        <label for="start-date" class="form-label">开始日期</label>
                        <input type="date" class="form-control" id="start-date">
                    </div>
                    <div class="col-md-3 mb-3">
                        <label for="end-date" class="form-label">结束日期</label>
                        <input type="date" class="form-control" id="end-date">
                    </div>
                    <div class="col-md-3 mb-3">
                        <label for="author-select" class="form-label">作者</label>
                        <select class="form-select" id="author-select">
                            <option value="">所有作者</option>
                        </select>
                    </div>
                    <div class="col-md-3 mb-3">
                        <label for="project-select" class="form-label">项目</label>
                        <select class="form-select" id="project-select">
                            <option value="">所有项目</option>
                        </select>
                    </div>
                </div>
                <div class="row">
                    <div class="col-12 text-center">
                        <button class="btn btn-primary" id="search-btn">查询</button>
                        <button class="btn btn-secondary ms-2" id="reset-btn">重置</button>
                    </div>
                </div>
            </div>
            
            <div class="card mb-4">
                <div class="card-header">数据列表</div>
                <div class="card-body">
                    <div id="loading-indicator" class="text-center my-3" style="display: none;">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">加载中...</span>
                        </div>
                        <p class="mt-2">正在查询数据，请稍候...</p>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-striped table-hover">
                            <thead>
                                <tr>
                                    <th class="project-column">项目名称</th>
                                    <th class="author-column">作者</th>
                                    <th class="time-column">更新时间</th>
                                    <th class="message-column">提交信息</th>
                                    <th class="score-column">分数</th>
                                    <th class="action-column">查看评审</th>
                                </tr>
                            </thead>
                            <tbody id="logs-table-body">
                            </tbody>
                        </table>
                    </div>
                    <div class="text-center mt-4">
                        <div id="pagination" class="btn-group"></div>
                    </div>
                </div>
            </div>
            
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">项目提交次数</div>
                        <div class="card-body">
                            <div id="project-count-chart" class="chart-container"></div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">项目平均分数</div>
                        <div class="card-body">
                            <div id="project-score-chart" class="chart-container"></div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">作者提交次数</div>
                        <div class="card-body">
                            <div id="author-count-chart" class="chart-container"></div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">作者平均分数</div>
                        <div class="card-body">
                            <div id="author-score-chart" class="chart-container"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            // 定义全局变量
            let allData = [];
            let currentPage = 1;
            const pageSize = 10;
            
            // 初始化日期选择器
            const today = new Date();
            const lastWeek = new Date();
            lastWeek.setDate(today.getDate() - 7);
            
            document.getElementById('start-date').valueAsDate = lastWeek;
            document.getElementById('end-date').valueAsDate = today;
            
            // 格式化日期
            function formatDate(timestamp) {
                const date = new Date(timestamp * 1000);
                return date.toLocaleString('zh-CN');
            }
            
            // 获取数据
            function fetchData() {
                const startDate = document.getElementById('start-date').value;
                const endDate = document.getElementById('end-date').value;
                const author = document.getElementById('author-select').value;
                const project = document.getElementById('project-select').value;
                
                // 显示加载指示器，隐藏表格和分页
                document.getElementById('loading-indicator').style.display = 'block';
                document.querySelector('.table-responsive').style.display = 'none';
                document.getElementById('pagination').parentElement.style.display = 'none';
                
                let url = '/api/review/push_logs?';
                if (startDate) url += `start_date=${startDate}&`;
                if (endDate) url += `end_date=${endDate}&`;
                if (author) url += `authors=${encodeURIComponent(author)}&`;
                if (project) url += `project_names=${encodeURIComponent(project)}&`;
                
                fetch(url)
                    .then(response => response.json())
                    .then(data => {
                        allData = data;
                        currentPage = 1;
                        
                        // 隐藏加载指示器，显示表格和分页
                        document.getElementById('loading-indicator').style.display = 'none';
                        document.querySelector('.table-responsive').style.display = 'block';
                        document.getElementById('pagination').parentElement.style.display = 'block';
                        
                        renderTable();
                        renderCharts();
                    })
                    .catch(error => {
                        // 隐藏加载指示器，显示表格
                        document.getElementById('loading-indicator').style.display = 'none';
                        document.querySelector('.table-responsive').style.display = 'block';
                        document.getElementById('pagination').parentElement.style.display = 'block';
                        
                        console.error('获取数据失败:', error);
                        alert('获取数据失败，请查看控制台获取详细信息');
                    });
            }
            
            // 渲染表格
            function renderTable() {
                const tableBody = document.getElementById('logs-table-body');
                const startIndex = (currentPage - 1) * pageSize;
                const endIndex = startIndex + pageSize;
                const pageData = allData.slice(startIndex, endIndex);
                
                tableBody.innerHTML = '';
                
                if (pageData.length === 0) {
                    const row = document.createElement('tr');
                    row.innerHTML = '<td colspan="6" class="text-center">没有数据</td>';
                    tableBody.appendChild(row);
                    document.getElementById('pagination').innerHTML = '';
                    return;
                }
                
                pageData.forEach(item => {
                    const row = document.createElement('tr');
                    
                    row.innerHTML = `
                        <td class="project-column">${item.project_name}</td>
                        <td class="author-column">${item.author}</td>
                        <td class="time-column">${item.updated_at_format || item.updated_at}</td>
                        <td class="message-column">${item.commit_messages}</td>
                        <td class="score-column">
                            <div class="score-progress">
                                <div class="progress-bar" role="progressbar" style="width: ${item.score}%;" 
                                    aria-valuenow="${item.score}" aria-valuemin="0" aria-valuemax="100">
                                    ${item.score}
                                </div>
                            </div>
                        </td>
                        <td class="action-column">
                            <a href="/review/push_result/${item.id}" class="review-btn" target="_blank">查看评审</a>
                        </td>
                    `;
                    
                    tableBody.appendChild(row);
                });
                
                renderPagination();
            }
            
            // 渲染分页
            function renderPagination() {
                const paginationContainer = document.getElementById('pagination');
                paginationContainer.innerHTML = '';
                
                const totalPages = Math.ceil(allData.length / pageSize);
                
                for (let i = 1; i <= totalPages; i++) {
                    const button = document.createElement('button');
                    button.className = `btn btn-sm ${i === currentPage ? 'btn-primary' : 'btn-outline-primary'}`;
                    button.innerText = i;
                    button.addEventListener('click', () => {
                        currentPage = i;
                        renderTable();
                    });
                    paginationContainer.appendChild(button);
                }
            }
            
            // 渲染图表
            function renderCharts() {
                if (allData.length === 0) return;
                
                // 项目提交次数图表
                const projectCountMap = {};
                allData.forEach(item => {
                    if (!projectCountMap[item.project_name]) {
                        projectCountMap[item.project_name] = 0;
                    }
                    projectCountMap[item.project_name]++;
                });
                
                const projectCountChart = echarts.init(document.getElementById('project-count-chart'));
                projectCountChart.setOption({
                    tooltip: {
                        trigger: 'axis'
                    },
                    xAxis: {
                        type: 'category',
                        data: Object.keys(projectCountMap),
                        axisLabel: {
                            rotate: 45
                        }
                    },
                    yAxis: {
                        type: 'value'
                    },
                    series: [{
                        name: '提交次数',
                        type: 'bar',
                        data: Object.values(projectCountMap)
                    }]
                });
                
                // 项目平均分数图表
                const projectScoreMap = {};
                const projectScoreCountMap = {};
                allData.forEach(item => {
                    if (!projectScoreMap[item.project_name]) {
                        projectScoreMap[item.project_name] = 0;
                        projectScoreCountMap[item.project_name] = 0;
                    }
                    projectScoreMap[item.project_name] += item.score;
                    projectScoreCountMap[item.project_name]++;
                });
                
                const projectScoreAvgMap = {};
                Object.keys(projectScoreMap).forEach(key => {
                    projectScoreAvgMap[key] = projectScoreMap[key] / projectScoreCountMap[key];
                });
                
                const projectScoreChart = echarts.init(document.getElementById('project-score-chart'));
                projectScoreChart.setOption({
                    tooltip: {
                        trigger: 'axis'
                    },
                    xAxis: {
                        type: 'category',
                        data: Object.keys(projectScoreAvgMap),
                        axisLabel: {
                            rotate: 45
                        }
                    },
                    yAxis: {
                        type: 'value',
                        max: 100
                    },
                    series: [{
                        name: '平均分数',
                        type: 'bar',
                        data: Object.values(projectScoreAvgMap)
                    }]
                });
                
                // 作者提交次数图表
                const authorCountMap = {};
                allData.forEach(item => {
                    if (!authorCountMap[item.author]) {
                        authorCountMap[item.author] = 0;
                    }
                    authorCountMap[item.author]++;
                });
                
                const authorCountChart = echarts.init(document.getElementById('author-count-chart'));
                authorCountChart.setOption({
                    tooltip: {
                        trigger: 'axis'
                    },
                    xAxis: {
                        type: 'category',
                        data: Object.keys(authorCountMap),
                        axisLabel: {
                            rotate: 45
                        }
                    },
                    yAxis: {
                        type: 'value'
                    },
                    series: [{
                        name: '提交次数',
                        type: 'bar',
                        data: Object.values(authorCountMap)
                    }]
                });
                
                // 作者平均分数图表
                const authorScoreMap = {};
                const authorScoreCountMap = {};
                allData.forEach(item => {
                    if (!authorScoreMap[item.author]) {
                        authorScoreMap[item.author] = 0;
                        authorScoreCountMap[item.author] = 0;
                    }
                    authorScoreMap[item.author] += item.score;
                    authorScoreCountMap[item.author]++;
                });
                
                const authorScoreAvgMap = {};
                Object.keys(authorScoreMap).forEach(key => {
                    authorScoreAvgMap[key] = authorScoreMap[key] / authorScoreCountMap[key];
                });
                
                const authorScoreChart = echarts.init(document.getElementById('author-score-chart'));
                authorScoreChart.setOption({
                    tooltip: {
                        trigger: 'axis'
                    },
                    xAxis: {
                        type: 'category',
                        data: Object.keys(authorScoreAvgMap),
                        axisLabel: {
                            rotate: 45
                        }
                    },
                    yAxis: {
                        type: 'value',
                        max: 100
                    },
                    series: [{
                        name: '平均分数',
                        type: 'bar',
                        data: Object.values(authorScoreAvgMap)
                    }]
                });
                
                // 更新筛选条件选项
                updateFilterOptions();
                
                // 监听窗口大小变化
                window.addEventListener('resize', () => {
                    projectCountChart.resize();
                    projectScoreChart.resize();
                    authorCountChart.resize();
                    authorScoreChart.resize();
                });
            }
            
            // 更新筛选条件下拉选项
            function updateFilterOptions() {
                const authorSelect = document.getElementById('author-select');
                const projectSelect = document.getElementById('project-select');
                
                // 保存现有选择
                const selectedAuthor = authorSelect.value;
                const selectedProject = projectSelect.value;
                
                // 清空现有选项，但保留"所有作者/项目"选项
                authorSelect.innerHTML = '<option value="">所有作者</option>';
                projectSelect.innerHTML = '<option value="">所有项目</option>';
                
                // 获取不重复的作者和项目
                const authors = new Set();
                const projects = new Set();
                
                allData.forEach(item => {
                    if (item.author) authors.add(item.author);
                    if (item.project_name) projects.add(item.project_name);
                });
                
                // 添加作者选项
                authors.forEach(author => {
                    const option = document.createElement('option');
                    option.value = author;
                    option.text = author;
                    if (author === selectedAuthor) option.selected = true;
                    authorSelect.appendChild(option);
                });
                
                // 添加项目选项
                projects.forEach(project => {
                    const option = document.createElement('option');
                    option.value = project;
                    option.text = project;
                    if (project === selectedProject) option.selected = true;
                    projectSelect.appendChild(option);
                });
            }
            
            // 重置筛选条件
            function resetFilters() {
                document.getElementById('start-date').valueAsDate = lastWeek;
                document.getElementById('end-date').valueAsDate = today;
                document.getElementById('author-select').value = "";
                document.getElementById('project-select').value = "";
                fetchData();
            }
            
            // 绑定事件
            document.getElementById('search-btn').addEventListener('click', fetchData);
            document.getElementById('reset-btn').addEventListener('click', resetFilters);
            
            // 初始加载数据
            fetchData();
        </script>
    </body>
    </html>
    """
    return html_content


@api_app.route('/review/daily_report', methods=['GET'])
def daily_report():
    # 获取当前日期0点和23点59分59秒的时间戳
    start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end_time = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0).timestamp()

    try:
        if push_review_enabled:
            df = ReviewService().get_push_review_logs(updated_at_gte=start_time, updated_at_lte=end_time)
        else:
            df = ReviewService().get_mr_review_logs(updated_at_gte=start_time, updated_at_lte=end_time)

        if df.empty:
            logger.info("No data to process.")
            return jsonify({'message': 'No data to process.'}), 200
        # 去重：基于 (author, message) 组合
        df_unique = df.drop_duplicates(subset=["author", "commit_messages"])
        # 按照 author 排序
        df_sorted = df_unique.sort_values(by="author")
        # 转换为适合生成日报的格式
        commits = df_sorted.to_dict(orient="records")
        # 生成日报内容
        report_txt = Reporter().generate_report(json.dumps(commits))
        # 发送钉钉通知
        notifier.send_notification(content=report_txt, msg_type="markdown", title="代码提交日报")

        # 返回生成的日报内容
        return json.dumps(report_txt, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")
        return jsonify({'message': f"Failed to generate daily report: {e}"}), 500


def setup_scheduler():
    """
    配置并启动定时任务调度器
    """
    try:
        scheduler = BackgroundScheduler()
        crontab_expression = os.getenv('REPORT_CRONTAB_EXPRESSION', '0 18 * * 1-5')
        cron_parts = crontab_expression.split()
        cron_minute, cron_hour, cron_day, cron_month, cron_day_of_week = cron_parts

        # Schedule the task based on the crontab expression
        scheduler.add_job(
            daily_report,
            trigger=CronTrigger(
                minute=cron_minute,
                hour=cron_hour,
                day=cron_day,
                month=cron_month,
                day_of_week=cron_day_of_week
            )
        )

        # Start the scheduler
        scheduler.start()
        logger.info("Scheduler started successfully.")

        # Shut down the scheduler when exiting the app
        atexit.register(lambda: scheduler.shutdown())
    except Exception as e:
        logger.error(f"Error setting up scheduler: {e}")
        logger.error(traceback.format_exc())


# 处理 GitLab Merge Request Webhook
@api_app.route('/review/webhook', methods=['POST'])
def handle_webhook():
    # 获取请求的JSON数据
    if request.is_json:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        # 判断是GitLab还是GitHub的webhook
        webhook_source = request.headers.get('X-GitHub-Event')
        
        if webhook_source:  # GitHub webhook
            return handle_github_webhook(webhook_source, data)
        else:  # GitLab webhook
            return handle_gitlab_webhook(data)
    else:
        return jsonify({'message': 'Invalid data format'}), 400

def handle_github_webhook(event_type, data):
    # 获取GitHub配置
    github_token = os.getenv('GITHUB_ACCESS_TOKEN') or request.headers.get('X-GitHub-Token')
    if not github_token:
        return jsonify({'message': 'Missing GitHub access token'}), 400
        
    github_url = os.getenv('GITHUB_URL') or 'https://github.com'
    github_url_slug = slugify_url(github_url)
    
    # 打印整个payload数据
    logger.info(f'Received GitHub event: {event_type}')
    logger.info(f'Payload: {json.dumps(data)}')
    
    if event_type == "pull_request":
        # 使用handle_queue进行异步处理
        handle_queue(handle_github_pull_request_event, data, github_token, github_url, github_url_slug)
        # 立马返回响应
        return jsonify({'message': f'GitHub request received(event_type={event_type}), will process asynchronously.'}), 200
    elif event_type == "push":
        # 使用handle_queue进行异步处理
        handle_queue(handle_github_push_event, data, github_token, github_url, github_url_slug)
        # 立马返回响应
        return jsonify({'message': f'GitHub request received(event_type={event_type}), will process asynchronously.'}), 200
    else:
        error_message = f'Only pull_request and push events are supported for GitHub webhook, but received: {event_type}.'
        logger.error(error_message)
        return jsonify(error_message), 400

def handle_gitlab_webhook(data):
    object_kind = data.get("object_kind")

    # 优先从请求头获取，如果没有，则从环境变量获取，如果没有，则从推送事件中获取
    gitlab_url = os.getenv('GITLAB_URL') or request.headers.get('X-Gitlab-Instance')
    if not gitlab_url:
        repository = data.get('repository')
        if not repository:
            return jsonify({'message': 'Missing GitLab URL'}), 400
        homepage = repository.get("homepage")
        if not homepage:
            return jsonify({'message': 'Missing GitLab URL'}), 400
        try:
            parsed_url = urlparse(homepage)
            gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        except Exception as e:
            return jsonify({"error": f"Failed to parse homepage URL: {str(e)}"}), 400

    # 优先从环境变量获取，如果没有，则从请求头获取
    gitlab_token = os.getenv('GITLAB_ACCESS_TOKEN') or request.headers.get('X-Gitlab-Token')
    # 如果gitlab_token为空，返回错误
    if not gitlab_token:
        return jsonify({'message': 'Missing GitLab access token'}), 400

    gitlab_url_slug = slugify_url(gitlab_url)

    # 打印整个payload数据，或根据需求进行处理
    logger.info(f'Received event: {object_kind}')
    logger.info(f'Payload: {json.dumps(data)}')

    # 处理Merge Request Hook
    if object_kind == "merge_request":
        # 创建一个新进程进行异步处理
        handle_queue(handle_merge_request_event, data, gitlab_token, gitlab_url, gitlab_url_slug)
        # 立马返回响应
        return jsonify(
            {'message': f'Request received(object_kind={object_kind}), will process asynchronously.'}), 200
    elif object_kind == "push":
        # 创建一个新进程进行异步处理
        # TODO check if PUSH_REVIEW_ENABLED is needed here
        handle_queue(handle_push_event, data, gitlab_token, gitlab_url, gitlab_url_slug)
        # 立马返回响应
        return jsonify(
            {'message': f'Request received(object_kind={object_kind}), will process asynchronously.'}), 200
    else:
        error_message = f'Only merge_request and push events are supported (both Webhook and System Hook), but received: {object_kind}.'
        logger.error(error_message)
        return jsonify(error_message), 400

if __name__ == '__main__':
    check_config()
    # 启动定时任务调度器
    setup_scheduler()

    # 确保静态文件夹存在
    os.makedirs('static', exist_ok=True)

    # 启动Flask API服务
    port = int(os.environ.get('SERVER_PORT', 5001))
    api_app.run(host='0.0.0.0', port=port)
