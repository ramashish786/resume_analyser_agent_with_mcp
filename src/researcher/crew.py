import os
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import PDFSearchTool, MCPServerAdapter
from mcp import StdioServerParameters
from crewai.agents.agent_builder.base_agent import BaseAgent

from pydantic import BaseModel

class CriteriaScores(BaseModel):
    skill: int
    yof: int
    role_alignment: int

class FinalScore(BaseModel):
    score: float

class EmailResult(BaseModel):
    status: str
    score: float
    email_type: str
    to: str
    subject: str

server_params = StdioServerParameters(
    command="uv",
    args=[
        "--directory",
        "D:\\machine_learning\\test_projects\\genai\\udemy\\crewai\\researcher\\src\\researcher\\tools",
        "run", "fastmcp", "run", "custom_tool.py",
    ],
    env=os.environ.copy(),
)


@CrewBase
class Researcher():
    """Researcher crew - configured per-resume."""

    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(self, resume_path: str):
        """Build a crew bound to ONE resume PDF.

        Args:
            resume_path: absolute path to the candidate's resume PDF.
        """
        self.resume_path = resume_path
        self.pdf_search_tool = PDFSearchTool(pdf=resume_path)

        # MCP adapter: one connection per crew instance.
        self._mcp_adapter = MCPServerAdapter(server_params)
        self.mcp_tools = self._mcp_adapter.__enter__()

    def close(self):
        """Cleanly close the MCP connection. Call after kickoff."""
        try:
            self._mcp_adapter.__exit__(None, None, None)
        except Exception as e:
            print(f"Warning: error closing MCP adapter: {e}")

    @agent
    def recruiter_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['recruiter_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[self.pdf_search_tool],
        )

    @agent
    def reporting_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['reporting_analyst'],
            verbose=True,
        )

    @agent
    def scoring_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['scoring_agent'],
            verbose=True,
            tools=self.mcp_tools,
        )

    @agent
    def send_mail_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['send_mail_agent'],
            verbose=True,
            tools=self.mcp_tools,
        )

    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'],
            tools=[self.pdf_search_tool],
        )

    @task
    def reporting_task(self) -> Task:
        return Task(config=self.tasks_config['reporting_task'],
                    output_pydantic=CriteriaScores,)

    @task
    def scoring_task(self) -> Task:
        return Task(
            config=self.tasks_config['scoring_task'],
            tools=self.mcp_tools,
            output_pydantic=FinalScore,
        )

    @task
    def send_mail_task(self) -> Task:
        #candidate_id = os.path.splitext(os.path.basename(self.resume_path))[0]
        return Task(
            config=self.tasks_config['send_mail_task'],
            tools=self.mcp_tools,
            output_pydantic=EmailResult,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )