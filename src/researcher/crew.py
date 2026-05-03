import os
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import PDFSearchTool, MCPServerAdapter
from mcp import StdioServerParameters
from crewai.agents.agent_builder.base_agent import BaseAgent

server_params = StdioServerParameters(
    command="uv",
    args=["--directory", "D:\\machine_learning\\test_projects\\genai\\udemy\\crewai\\researcher\\src\\researcher\\tools",
          "run", "fastmcp", "run", "custom_tool.py"],
    env=os.environ.copy() 
)

file_location = "D:\\machine_learning\\test_projects\\genai\\udemy\\crewai\\researcher\\knowledge\\Ramashish_Sahani_Resume.pdf"
pdf_search_tool = PDFSearchTool(pdf=file_location)


@CrewBase
class Researcher():
    """Researcher crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(self):
        self._mcp_adapter = MCPServerAdapter(server_params)
        self.mcp_tools = self._mcp_adapter.__enter__() 

    def __del__(self):
        try:
            self._mcp_adapter.__exit__(None, None, None)
        except Exception:
            pass

    @agent
    def recruiter_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['recruiter_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[pdf_search_tool]
        )

    @agent
    def reporting_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['reporting_analyst'],
            verbose=True,
        )

    @agent
    def grading_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['grading_agent'],
            verbose=True,
            tools=self.mcp_tools  # ✅ Now accessible
        )

    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'],
            tools=[pdf_search_tool]
        )

    @task
    def reporting_task(self) -> Task:
        return Task(config=self.tasks_config['reporting_task'])

    @task
    def grading_task(self) -> Task:
        return Task(
            config=self.tasks_config['grading_task'],
            tools=self.mcp_tools,
            output_file='output/report.json'
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True  # ✅ Fix 2: removed tracing=True
        )