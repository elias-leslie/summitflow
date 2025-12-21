"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Layers,
  Zap,
  CheckCircle2,
  ArrowRight,
  Workflow,
  Target,
  FileCode2,
  Camera,
  Terminal,
  GitBranch,
  Sparkles,
  Shield,
  BarChart3,
  Users,
} from "lucide-react";

type TabId = "overview" | "how-it-works" | "getting-started" | "features";

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const tabs: Tab[] = [
  { id: "overview", label: "Overview", icon: <Layers className="w-4 h-4" /> },
  { id: "how-it-works", label: "How It Works", icon: <Workflow className="w-4 h-4" /> },
  { id: "getting-started", label: "Getting Started", icon: <Zap className="w-4 h-4" /> },
  { id: "features", label: "Features", icon: <Sparkles className="w-4 h-4" /> },
];

export default function AboutPage() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  return (
    <div className="min-h-full overflow-auto">
      {/* Hero Section */}
      <section className="relative overflow-hidden">
        {/* Atmospheric background */}
        <div className="absolute inset-0 bg-gradient-to-b from-slate-900 via-slate-950 to-slate-950" />
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage: `
              radial-gradient(ellipse 80% 50% at 50% -20%, rgba(255, 102, 0, 0.15), transparent),
              radial-gradient(ellipse 60% 40% at 70% 10%, rgba(255, 0, 102, 0.1), transparent)
            `,
          }}
        />

        {/* Grid overlay */}
        <div
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage: `
              linear-gradient(to right, rgba(255, 0, 102, 0.08) 1px, transparent 1px),
              linear-gradient(to bottom, rgba(255, 0, 102, 0.08) 1px, transparent 1px)
            `,
            backgroundSize: "48px 48px",
            maskImage: "linear-gradient(to bottom, black 50%, transparent 100%)",
          }}
        />

        <div className="relative z-10 max-w-6xl mx-auto px-8 pt-16 pb-12">
          {/* Logo mark */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6 }}
            className="flex items-center gap-3 mb-8"
          >
            <div
              className="w-12 h-12 rounded-2xl flex items-center justify-center"
              style={{
                background: "linear-gradient(135deg, rgba(255, 102, 0, 0.2) 0%, rgba(255, 0, 102, 0.2) 100%)",
                border: "1px solid rgba(255, 102, 0, 0.3)",
                boxShadow: "0 0 30px rgba(255, 102, 0, 0.15)",
              }}
            >
              <Target className="w-6 h-6 text-sunset-orange" />
            </div>
            <span className="text-sm font-medium tracking-widest uppercase text-slate-500">
              AI Development Platform
            </span>
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="display text-5xl md:text-6xl font-bold tracking-tight mb-6"
            style={{
              background: "linear-gradient(135deg, #ffffff 0%, #94a3b8 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Build Software with
            <br />
            <span
              style={{
                background: "linear-gradient(90deg, #fff200 0%, #ff6600 50%, #ff0066 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Autonomous Intelligence
            </span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="text-xl text-slate-400 max-w-2xl leading-relaxed mb-10"
          >
            SummitFlow orchestrates AI agents to execute development tasks with precision.
            Define your vision, track progress through features and tasks, and let intelligent
            automation handle the implementation.
          </motion.p>

          {/* Trust indicators */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="flex flex-wrap gap-6 text-sm text-slate-500"
          >
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-phosphor-500" />
              <span>Self-Hosted & Secure</span>
            </div>
            <div className="flex items-center gap-2">
              <GitBranch className="w-4 h-4 text-phosphor-500" />
              <span>Git-Native Workflow</span>
            </div>
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-phosphor-500" />
              <span>Evidence-Based Progress</span>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Tab Navigation */}
      <section className="sticky top-0 z-20 bg-slate-950/95 backdrop-blur-sm border-b border-slate-800">
        <div className="max-w-6xl mx-auto px-8">
          <nav className="flex gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  relative px-5 py-4 flex items-center gap-2 text-sm font-medium transition-colors
                  ${activeTab === tab.id
                    ? "text-white"
                    : "text-slate-500 hover:text-slate-300"
                  }
                `}
              >
                {tab.icon}
                {tab.label}
                {activeTab === tab.id && (
                  <motion.div
                    layoutId="about-tab-indicator"
                    className="absolute bottom-0 left-0 right-0 h-0.5"
                    style={{
                      background: "linear-gradient(90deg, #ff6600 0%, #ff0066 100%)",
                    }}
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  />
                )}
              </button>
            ))}
          </nav>
        </div>
      </section>

      {/* Tab Content */}
      <section className="max-w-6xl mx-auto px-8 py-12">
        <AnimatePresence mode="wait">
          {activeTab === "overview" && <OverviewTab key="overview" />}
          {activeTab === "how-it-works" && <HowItWorksTab key="how-it-works" />}
          {activeTab === "getting-started" && <GettingStartedTab key="getting-started" />}
          {activeTab === "features" && <FeaturesTab key="features" />}
        </AnimatePresence>
      </section>

      {/* Footer CTA */}
      <section className="border-t border-slate-800">
        <div className="max-w-6xl mx-auto px-8 py-16 text-center">
          <h2 className="display text-2xl font-semibold text-white mb-4">
            Ready to transform your development workflow?
          </h2>
          <p className="text-slate-400 mb-8 max-w-lg mx-auto">
            Get started with SummitFlow today and experience the future of AI-assisted software development.
          </p>
          <a
            href="/"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium text-white transition-all"
            style={{
              background: "linear-gradient(135deg, #ff6600 0%, #ff0066 100%)",
              boxShadow: "0 0 30px rgba(255, 102, 0, 0.3)",
            }}
          >
            Go to Dashboard
            <ArrowRight className="w-4 h-4" />
          </a>
        </div>
      </section>
    </div>
  );
}

// Tab Components
function OverviewTab() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* What is SummitFlow */}
      <div className="grid md:grid-cols-2 gap-12 items-center">
        <div>
          <h2 className="display text-3xl font-semibold text-white mb-4">
            What is SummitFlow?
          </h2>
          <p className="text-slate-400 leading-relaxed mb-6">
            SummitFlow is a task-driven development platform that bridges human vision and
            AI execution. It provides a structured environment where AI agents can autonomously
            work on well-defined tasks while maintaining full visibility and control for developers.
          </p>
          <ul className="space-y-3">
            {[
              "Feature-based project organization",
              "Hierarchical task management with dependencies",
              "Evidence capture for verification",
              "Intelligent code exploration",
            ].map((item, i) => (
              <li key={i} className="flex items-center gap-3 text-slate-300">
                <CheckCircle2 className="w-5 h-5 text-phosphor-500 flex-shrink-0" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        {/* Screenshot placeholder */}
        <ScreenshotPlaceholder
          label="Dashboard Overview"
          description="Project cards with task stats and activity feed"
        />
      </div>

      {/* Core Concepts */}
      <div>
        <h2 className="display text-3xl font-semibold text-white mb-8 text-center">
          Core Concepts
        </h2>
        <div className="grid md:grid-cols-3 gap-6">
          <ConceptCard
            icon={<Target className="w-6 h-6" />}
            title="Features"
            description="High-level capabilities with acceptance criteria. Features define what success looks like and group related tasks together."
            color="orange"
          />
          <ConceptCard
            icon={<CheckCircle2 className="w-6 h-6" />}
            title="Tasks"
            description="Actionable work items with clear objectives. Tasks can have dependencies, priorities, and are tracked through their lifecycle."
            color="pink"
          />
          <ConceptCard
            icon={<Camera className="w-6 h-6" />}
            title="Evidence"
            description="Screenshots and artifacts that prove work is complete. Evidence links directly to acceptance criteria for verification."
            color="cyan"
          />
        </div>
      </div>

      {/* Architecture diagram */}
      <div>
        <h2 className="display text-3xl font-semibold text-white mb-8 text-center">
          Architecture
        </h2>
        <ArchitectureDiagram />
      </div>
    </motion.div>
  );
}

function HowItWorksTab() {
  const steps = [
    {
      number: "01",
      title: "Define Your Vision",
      description: "Start by creating a project and defining features with clear acceptance criteria. This provides the structure AI agents need to work effectively.",
      icon: <Target className="w-5 h-5" />,
    },
    {
      number: "02",
      title: "Create Tasks",
      description: "Break features into tasks with priorities and dependencies. Use labels for complexity and domain to help agents understand the work.",
      icon: <Layers className="w-5 h-5" />,
    },
    {
      number: "03",
      title: "AI Execution",
      description: "AI agents claim tasks, execute implementation, and capture evidence. The integrated terminal provides full visibility into agent actions.",
      icon: <Terminal className="w-5 h-5" />,
    },
    {
      number: "04",
      title: "Review & Verify",
      description: "Review captured evidence against acceptance criteria. Approve, request changes, or provide feedback to guide further development.",
      icon: <CheckCircle2 className="w-5 h-5" />,
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* Workflow steps */}
      <div className="relative">
        {/* Connecting line */}
        <div
          className="absolute left-8 top-16 bottom-16 w-px hidden md:block"
          style={{
            background: "linear-gradient(to bottom, #ff6600, #ff0066)",
            opacity: 0.3,
          }}
        />

        <div className="space-y-12">
          {steps.map((step, i) => (
            <motion.div
              key={step.number}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className="flex gap-8 items-start"
            >
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center flex-shrink-0 relative z-10"
                style={{
                  background: "linear-gradient(135deg, rgba(255, 102, 0, 0.15) 0%, rgba(255, 0, 102, 0.15) 100%)",
                  border: "1px solid rgba(255, 102, 0, 0.2)",
                }}
              >
                <span
                  className="text-xl font-bold"
                  style={{
                    background: "linear-gradient(135deg, #ff6600 0%, #ff0066 100%)",
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                  }}
                >
                  {step.number}
                </span>
              </div>
              <div className="flex-1 pt-2">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-sunset-orange">{step.icon}</span>
                  <h3 className="display text-xl font-semibold text-white">{step.title}</h3>
                </div>
                <p className="text-slate-400 leading-relaxed max-w-xl">{step.description}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Workflow visualization */}
      <div>
        <h2 className="display text-2xl font-semibold text-white mb-8 text-center">
          Task Lifecycle
        </h2>
        <WorkflowVisualization />
      </div>
    </motion.div>
  );
}

function GettingStartedTab() {
  const commands = [
    {
      title: "Find available work",
      command: "st ready",
      description: "List tasks that are ready to be worked on",
    },
    {
      title: "Claim a task",
      command: "st update <id> --status running",
      description: "Mark a task as in progress",
    },
    {
      title: "Complete a task",
      command: "st close <id> --reason \"Done\"",
      description: "Close with a summary of what was done",
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* Quick start guide */}
      <div className="grid md:grid-cols-2 gap-12">
        <div>
          <h2 className="display text-3xl font-semibold text-white mb-4">
            Quick Start
          </h2>
          <p className="text-slate-400 leading-relaxed mb-8">
            SummitFlow uses a CLI tool called <code className="mono text-phosphor-400 bg-slate-800 px-2 py-0.5 rounded">st</code> for
            task management. Here are the essential commands to get started.
          </p>

          <div className="space-y-4">
            {commands.map((cmd, i) => (
              <motion.div
                key={cmd.command}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                className="p-4 rounded-lg border border-slate-800 bg-slate-900/50"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-white">{cmd.title}</span>
                </div>
                <code className="mono text-sm text-phosphor-400 block mb-2">{cmd.command}</code>
                <p className="text-xs text-slate-500">{cmd.description}</p>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Terminal preview */}
        <ScreenshotPlaceholder
          label="Terminal Interface"
          description="Integrated terminal with command history and output"
          dark
        />
      </div>

      {/* Setup steps */}
      <div>
        <h2 className="display text-2xl font-semibold text-white mb-8 text-center">
          Setup Checklist
        </h2>
        <div className="max-w-2xl mx-auto space-y-4">
          {[
            { step: "Install and configure services", done: true },
            { step: "Create your first project", done: true },
            { step: "Define features with acceptance criteria", done: false },
            { step: "Break features into tasks", done: false },
            { step: "Run your first AI agent session", done: false },
          ].map((item, i) => (
            <motion.div
              key={item.step}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className={`
                flex items-center gap-4 p-4 rounded-lg border transition-colors
                ${item.done
                  ? "border-phosphor-500/30 bg-phosphor-500/5"
                  : "border-slate-800 bg-slate-900/50"
                }
              `}
            >
              <div className={`
                w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0
                ${item.done
                  ? "bg-phosphor-500/20 text-phosphor-400"
                  : "bg-slate-800 text-slate-600"
                }
              `}>
                {item.done ? (
                  <CheckCircle2 className="w-4 h-4" />
                ) : (
                  <span className="text-xs font-medium">{i + 1}</span>
                )}
              </div>
              <span className={item.done ? "text-slate-300" : "text-slate-500"}>
                {item.step}
              </span>
            </motion.div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

function FeaturesTab() {
  const features = [
    {
      icon: <Layers className="w-6 h-6" />,
      title: "Feature Management",
      description: "Organize work into features with acceptance criteria. Track progress as tasks complete and evidence is captured.",
      color: "orange",
    },
    {
      icon: <CheckCircle2 className="w-6 h-6" />,
      title: "Task Tracking",
      description: "Hierarchical tasks with dependencies, priorities, and labels. Full lifecycle management from creation to completion.",
      color: "pink",
    },
    {
      icon: <FileCode2 className="w-6 h-6" />,
      title: "Code Explorer",
      description: "Navigate your codebase with intelligent analysis. View files, database tables, API endpoints, and Celery tasks.",
      color: "cyan",
    },
    {
      icon: <Camera className="w-6 h-6" />,
      title: "Evidence Capture",
      description: "Screenshot and artifact capture linked to acceptance criteria. Version-controlled evidence for verification.",
      color: "yellow",
    },
    {
      icon: <Terminal className="w-6 h-6" />,
      title: "Integrated Terminal",
      description: "Full terminal access with command history. Execute CLI commands, run tests, and interact with your project.",
      color: "purple",
    },
    {
      icon: <Users className="w-6 h-6" />,
      title: "Multi-Project Support",
      description: "Manage multiple projects from a single dashboard. Each project has isolated configuration and task tracking.",
      color: "green",
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* Feature grid */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {features.map((feature, i) => (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <FeatureCard {...feature} />
          </motion.div>
        ))}
      </div>

      {/* Feature showcase */}
      <div>
        <h2 className="display text-2xl font-semibold text-white mb-8 text-center">
          Feature Showcase
        </h2>
        <div className="grid md:grid-cols-2 gap-8">
          <ScreenshotPlaceholder
            label="Kanban Board"
            description="Visual task management with drag-and-drop"
          />
          <ScreenshotPlaceholder
            label="Evidence Gallery"
            description="Browse and review captured screenshots"
          />
        </div>
      </div>
    </motion.div>
  );
}

// Reusable Components
interface ConceptCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  color: "orange" | "pink" | "cyan";
}

function ConceptCard({ icon, title, description, color }: ConceptCardProps) {
  const colors = {
    orange: { bg: "rgba(255, 102, 0, 0.1)", border: "rgba(255, 102, 0, 0.2)", text: "#ff6600" },
    pink: { bg: "rgba(255, 0, 102, 0.1)", border: "rgba(255, 0, 102, 0.2)", text: "#ff0066" },
    cyan: { bg: "rgba(0, 245, 255, 0.1)", border: "rgba(0, 245, 255, 0.2)", text: "#00f5ff" },
  };

  const c = colors[color];

  return (
    <div
      className="p-6 rounded-xl border transition-all hover:scale-[1.02]"
      style={{
        background: c.bg,
        borderColor: c.border,
      }}
    >
      <div
        className="w-12 h-12 rounded-lg flex items-center justify-center mb-4"
        style={{ color: c.text, background: `${c.bg}` }}
      >
        {icon}
      </div>
      <h3 className="display text-lg font-semibold text-white mb-2">{title}</h3>
      <p className="text-slate-400 text-sm leading-relaxed">{description}</p>
    </div>
  );
}

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  color: string;
}

function FeatureCard({ icon, title, description, color }: FeatureCardProps) {
  const colorMap: Record<string, string> = {
    orange: "#ff6600",
    pink: "#ff0066",
    cyan: "#00f5ff",
    yellow: "#fff200",
    purple: "#bf00ff",
    green: "#00ff88",
  };

  const c = colorMap[color] || colorMap.orange;

  return (
    <div
      className="p-6 rounded-xl border border-slate-800 bg-slate-900/50 hover:bg-slate-900 transition-colors group"
    >
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center mb-4 transition-transform group-hover:scale-110"
        style={{
          color: c,
          background: `${c}15`,
          border: `1px solid ${c}30`,
        }}
      >
        {icon}
      </div>
      <h3 className="display text-lg font-semibold text-white mb-2">{title}</h3>
      <p className="text-slate-400 text-sm leading-relaxed">{description}</p>
    </div>
  );
}

interface ScreenshotPlaceholderProps {
  label: string;
  description: string;
  dark?: boolean;
}

function ScreenshotPlaceholder({ label, description, dark }: ScreenshotPlaceholderProps) {
  return (
    <div
      className="relative rounded-xl overflow-hidden border border-slate-700"
      style={{
        aspectRatio: "16/10",
        background: dark
          ? "linear-gradient(135deg, #0a0612 0%, #150d20 100%)"
          : "linear-gradient(135deg, #1a0a2e 0%, #251538 100%)",
      }}
    >
      {/* Simulated window chrome */}
      <div className="absolute top-0 left-0 right-0 h-8 bg-slate-900/80 flex items-center px-3 gap-2">
        <div className="w-3 h-3 rounded-full bg-rose-500/60" />
        <div className="w-3 h-3 rounded-full bg-amber-500/60" />
        <div className="w-3 h-3 rounded-full bg-emerald-500/60" />
        <span className="ml-4 text-xs text-slate-500 mono">{label}</span>
      </div>

      {/* Content area with grid pattern */}
      <div
        className="absolute inset-0 top-8 flex items-center justify-center"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(255, 0, 102, 0.05) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 0, 102, 0.05) 1px, transparent 1px)
          `,
          backgroundSize: "24px 24px",
        }}
      >
        <div className="text-center p-8">
          <div
            className="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center"
            style={{
              background: "linear-gradient(135deg, rgba(255, 102, 0, 0.1) 0%, rgba(255, 0, 102, 0.1) 100%)",
              border: "1px solid rgba(255, 102, 0, 0.2)",
            }}
          >
            <Camera className="w-8 h-8 text-slate-600" />
          </div>
          <p className="text-slate-500 text-sm">{description}</p>
          <p className="text-slate-600 text-xs mt-2 mono">Screenshot placeholder</p>
        </div>
      </div>
    </div>
  );
}

function ArchitectureDiagram() {
  return (
    <div
      className="p-8 rounded-xl border border-slate-800 bg-slate-900/50"
      style={{
        backgroundImage: `
          radial-gradient(circle at 20% 30%, rgba(255, 102, 0, 0.05) 0%, transparent 50%),
          radial-gradient(circle at 80% 70%, rgba(255, 0, 102, 0.05) 0%, transparent 50%)
        `,
      }}
    >
      <div className="grid grid-cols-3 gap-8 max-w-3xl mx-auto">
        {/* Frontend */}
        <div className="text-center">
          <div
            className="w-20 h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background: "linear-gradient(135deg, rgba(0, 245, 255, 0.15) 0%, rgba(0, 245, 255, 0.05) 100%)",
              border: "1px solid rgba(0, 245, 255, 0.3)",
            }}
          >
            <Layers className="w-10 h-10 text-phosphor-500" />
          </div>
          <h4 className="font-medium text-white mb-1">Frontend</h4>
          <p className="text-xs text-slate-500">Next.js + React</p>
        </div>

        {/* Backend */}
        <div className="text-center">
          <div
            className="w-20 h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background: "linear-gradient(135deg, rgba(255, 102, 0, 0.15) 0%, rgba(255, 102, 0, 0.05) 100%)",
              border: "1px solid rgba(255, 102, 0, 0.3)",
            }}
          >
            <Zap className="w-10 h-10 text-sunset-orange" />
          </div>
          <h4 className="font-medium text-white mb-1">Backend</h4>
          <p className="text-xs text-slate-500">FastAPI + Python</p>
        </div>

        {/* Database */}
        <div className="text-center">
          <div
            className="w-20 h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background: "linear-gradient(135deg, rgba(255, 0, 102, 0.15) 0%, rgba(255, 0, 102, 0.05) 100%)",
              border: "1px solid rgba(255, 0, 102, 0.3)",
            }}
          >
            <FileCode2 className="w-10 h-10 text-outrun-500" />
          </div>
          <h4 className="font-medium text-white mb-1">Database</h4>
          <p className="text-xs text-slate-500">PostgreSQL</p>
        </div>
      </div>

      {/* Connection lines */}
      <div className="flex justify-center mt-6">
        <div className="flex items-center gap-4 text-xs text-slate-600">
          <div className="flex items-center gap-2">
            <div className="w-8 h-px bg-gradient-to-r from-phosphor-500 to-sunset-orange" />
            <span>REST API</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-px bg-gradient-to-r from-sunset-orange to-outrun-500" />
            <span>SQL</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function WorkflowVisualization() {
  const states = [
    { name: "Pending", color: "#64748b" },
    { name: "Ready", color: "#00f5ff" },
    { name: "Running", color: "#ff6600" },
    { name: "Completed", color: "#00ff88" },
  ];

  return (
    <div className="flex items-center justify-center gap-4 flex-wrap">
      {states.map((state, i) => (
        <div key={state.name} className="flex items-center gap-4">
          <div
            className="px-6 py-3 rounded-lg border text-sm font-medium"
            style={{
              borderColor: `${state.color}40`,
              background: `${state.color}10`,
              color: state.color,
            }}
          >
            {state.name}
          </div>
          {i < states.length - 1 && (
            <ArrowRight className="w-5 h-5 text-slate-600" />
          )}
        </div>
      ))}
    </div>
  );
}
