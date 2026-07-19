import { useState } from "react";
import {
  ArrowRightOutlined,
  CheckCircleFilled,
  CloudServerOutlined,
  GithubOutlined,
  PullRequestOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import "./Landing.css";
import "./LandingTransition.css";

const views = [
  {
    label: "Nightly CI",
    icon: <CheckCircleFilled />,
    value: "96.4%",
    sub: "较昨日 +2.8%",
    bars: [38, 52, 46, 66, 58, 72, 67, 80, 74, 88, 82, 94],
  },
  {
    label: "PR 流水线",
    icon: <PullRequestOutlined />,
    value: "24",
    sub: "6 项等待处理",
    bars: [42, 48, 55, 49, 64, 59, 71, 68, 78, 73, 84, 89],
  },
  {
    label: "模型验证",
    icon: <RobotOutlined />,
    value: "16 / 18",
    sub: "最新回归稳定",
    bars: [50, 54, 57, 61, 59, 68, 72, 69, 78, 82, 85, 90],
  },
  {
    label: "NPU 资源",
    icon: <CloudServerOutlined />,
    value: "72%",
    sub: "资源区间健康",
    bars: [46, 55, 61, 66, 72, 69, 75, 79, 74, 76, 73, 72],
  },
];

function OperationsPanel() {
  const [active, setActive] = useState(0);
  const view = views[active];
  return (
    <div className="ops-panel">
      <header>
        <div>
          <span>COMMUNITY OPERATIONS</span>
          <strong>实时运营视图</strong>
        </div>
        <em>
          <i /> 数据已连接
        </em>
      </header>
      <div className="ops-body">
        <nav aria-label="预览数据类型">
          {views.map((item, index) => (
            <button
              key={item.label}
              className={active === index ? "active" : ""}
              onClick={() => setActive(index)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <section className="ops-content">
          <div className="ops-metric">
            <span>{view.label}</span>
            <strong>{view.value}</strong>
            <small>{view.sub}</small>
          </div>
          <div className="ops-chart">
            <header>
              <span>12 日健康趋势</span>
              <small>LIVE</small>
            </header>
            <div key={view.label}>
              {view.bars.map((height, index) => (
                <i
                  key={index}
                  aria-label={`第 ${index + 1} 日，健康度 ${height}%`}
                  data-value={`${height}%`}
                  style={{
                    height: `${height}%`,
                    animationDelay: `${index * 25}ms`,
                  }}
                />
              ))}
            </div>
          </div>
          <div className="ops-attention">
            <span>
              <ThunderboltOutlined /> 当前建议
            </span>
            <p>
              {active === 0
                ? "优先处理 2 个失败任务，再检查关联代码变更。"
                : active === 1
                  ? "集中评审等待时间最长的 3 个 PR。"
                  : active === 2
                    ? "复核两个待确认模型的精度回归结果。"
                    : "当前资源稳定，无需调整调度策略。"}
            </p>
            <ArrowRightOutlined />
          </div>
        </section>
      </div>
    </div>
  );
}

const capabilities = [
  {
    icon: <CheckCircleFilled />,
    eyebrow: "DELIVERY",
    title: "从全局健康度，下钻到每一次失败。",
    copy: "统一查看 Workflow、Job、日志与运行耗时，让交付风险不再藏在多个工具之间。",
    metric: "96.4%",
    metricLabel: "CI success rate",
    large: true,
  },
  {
    icon: <PullRequestOutlined />,
    eyebrow: "COLLABORATION",
    title: "看清 PR 推进中的真实阻塞。",
    copy: "把评审、检查和合并状态放在同一个上下文中。",
    metric: "24",
    metricLabel: "active pull requests",
  },
  {
    icon: <RobotOutlined />,
    eyebrow: "MODEL QUALITY",
    title: "持续跟踪模型质量与回归。",
    copy: "连接精度、性能、兼容性与版本变化。",
    metric: "18",
    metricLabel: "models covered",
  },
  {
    icon: <CloudServerOutlined />,
    eyebrow: "INFRASTRUCTURE",
    title: "让算力状态服务于工程决策。",
    copy: "观察 NPU 利用率、任务负载与资源健康。",
    metric: "72%",
    metricLabel: "NPU utilization",
  },
];

export default function Landing() {
  return (
    <main className="landing-page">
      <section className="landing-hero">
        <div className="hero-engineering-field" aria-hidden="true">
          <svg viewBox="0 0 1600 900" preserveAspectRatio="none">
            <defs>
              <linearGradient id="signal-path" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor="#7f8fbe" stopOpacity="0" />
                <stop offset="0.55" stopColor="#8f83d8" stopOpacity="0.72" />
                <stop offset="1" stopColor="#a99cff" stopOpacity="0.18" />
              </linearGradient>
              <filter id="hero-noise">
                <feTurbulence
                  type="fractalNoise"
                  baseFrequency="0.82"
                  numOctaves="3"
                  stitchTiles="stitch"
                />
              </filter>
            </defs>
            <g
              className="signal-routes"
              fill="none"
              stroke="url(#signal-path)"
              strokeWidth="1"
            >
              <path
                className="signal-route--primary"
                d="M-80 610 C250 604 390 700 650 637 S940 470 1115 483"
              />
              <path
                className="signal-route--primary"
                d="M-40 730 C265 730 430 754 665 665 S930 520 1115 505"
              />
              <path
                className="signal-route--primary"
                d="M180 900 C330 760 480 744 688 679 S936 548 1115 527"
              />
              <path
                className="signal-route--secondary"
                d="M560 900 C610 774 748 713 868 636 S1010 556 1115 547"
              />
              <path
                className="signal-route--secondary"
                d="M1600 690 C1440 650 1300 585 1115 548"
              />
              <path
                className="signal-route--secondary"
                d="M1600 358 C1438 370 1310 430 1115 482"
              />
            </g>
            <g className="signal-nodes" fill="#aea3f4">
              <circle cx="286" cy="648" r="2.5" />
              <circle cx="690" cy="638" r="2.5" />
              <circle className="signal-node--key" cx="962" cy="514" r="3" />
              <circle className="signal-node--key" cx="1115" cy="505" r="3.5" />
              <circle cx="1310" cy="430" r="2" />
            </g>
            <rect
              className="hero-noise"
              width="1600"
              height="900"
              filter="url(#hero-noise)"
            />
          </svg>
        </div>
        <nav className="landing-nav">
          <Link className="landing-logo" to="/" aria-label="vLLM Ascend 首页">
            <BrandMark />
          </Link>
          <div className="landing-nav-links">
            <a href="#capabilities">产品能力</a>
            <a href="#workflow">工作方式</a>
            <a
              href="https://github.com/vllm-project/vllm-ascend"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
          </div>
          <Link className="landing-login" to="/login">
            进入工作台 <ArrowRightOutlined />
          </Link>
        </nav>
        <div className="hero-layout">
          <div className="hero-copy">
            <span className="hero-kicker">
              <i /> BUILT FOR vLLM ASCEND
            </span>
            <h1>
              把社区工程信号，
              <br />
              <em>变成清晰行动。</em>
            </h1>
            <p>
              一个为维护者打造的工程运营工作台。统一连接
              CI、PR、模型验证、测试质量与算力资源，更快发现风险，更准确地决定下一步。
            </p>
            <div className="hero-actions">
              <Link className="primary" to="/login">
                进入工作台 <ArrowRightOutlined />
              </Link>
              <a
                href="https://github.com/vllm-project/vllm-ascend"
                target="_blank"
                rel="noreferrer"
              >
                <GithubOutlined /> 查看开源项目
              </a>
            </div>
            <div className="hero-meta">
              <span>
                <b>5</b> 类工程信号
              </span>
              <span>
                <b>24h</b> 持续观察
              </span>
              <span>
                <b>AI</b> 辅助诊断
              </span>
            </div>
          </div>
          <OperationsPanel />
        </div>
      </section>

      <section className="landing-intro">
        <span>ONE CONNECTED VIEW</span>
        <h2>
          不是展示更多数据，
          <br />
          而是减少判断成本。
        </h2>
        <p>
          把散落在不同系统中的工程活动组织成同一个决策界面，让团队看到相同的事实、优先级和行动方向。
        </p>
      </section>

      <section className="capability-bento" id="capabilities">
        {capabilities.map((item) => (
          <article className={item.large ? "large" : ""} key={item.eyebrow}>
            <div className="capability-icon">{item.icon}</div>
            <span>{item.eyebrow}</span>
            <h3>{item.title}</h3>
            <p>{item.copy}</p>
            <div className="capability-metric">
              <strong>{item.metric}</strong>
              <small>{item.metricLabel}</small>
            </div>
          </article>
        ))}
      </section>

      <section className="workflow-section" id="workflow">
        <header>
          <span>FROM SIGNAL TO ACTION</span>
          <h2>一条连续的问题解决路径。</h2>
          <p>减少工具切换，让每一次异常都能沿着明确路径走向解决与复盘。</p>
        </header>
        <div className="workflow-path">
          {[
            ["01", "发现", "从全景中识别异常与优先级"],
            ["02", "定位", "关联任务、日志、变更和资源"],
            ["03", "协作", "让不同角色共享同一上下文"],
            ["04", "复盘", "用趋势和日报验证改进效果"],
          ].map(([no, title, copy]) => (
            <article key={no}>
              <span>{no}</span>
              <i />
              <h3>{title}</h3>
              <p>{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-cta">
        <span>START WITH CLARITY</span>
        <h2>
          看清系统。
          <br />
          推动社区前进。
        </h2>
        <div>
          <Link to="/login">
            登录工作台 <ArrowRightOutlined />
          </Link>
          <Link to="/register">申请社区账号</Link>
        </div>
      </section>
      <footer className="landing-footer">
        <Link to="/" aria-label="vLLM Ascend 首页">
          <BrandMark />
        </Link>
        <p>Community Operations Dashboard</p>
        <a
          href="https://github.com/vllm-project/vllm-ascend"
          target="_blank"
          rel="noreferrer"
        >
          GitHub <ArrowRightOutlined />
        </a>
      </footer>
    </main>
  );
}
