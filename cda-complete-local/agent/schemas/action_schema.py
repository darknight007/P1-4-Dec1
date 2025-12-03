from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, model_validator

class AgentAction(BaseModel):
    """
    Structured decision output for the Specialist Agent.
    The agent must always return this structure.
    """
    thought: str = Field(
        "Processing action...",
        description="Clear reasoning for the decision. Explain 'Why' you are choosing this action. Identify gaps in current knowledge."
    )

    action_type: Literal["call_tool", "ask_human", "finish_phase"] = Field(
        ...,
        description="The type of action to take. 'call_tool' to execute a function. 'ask_human' if you are stuck or need validation. 'finish_phase' when the goal is met."
    )

    tool_name: Optional[str] = Field(
        None,
        description="The exact name of the tool to call (e.g., 'grep_codebase', 'read_file'). Required if action_type is 'call_tool'."
    )

    tool_args: Optional[Dict[str, Any]] = Field(
        None,
        description="The arguments for the tool call as a dictionary (e.g., {'patterns': ['aws'], 'root_path': '.'}). This field is REQUIRED if action_type is 'call_tool'."
    )

    human_question: Optional[str] = Field(
        None,
        description="The question to ask the user. Required if action_type is 'ask_human'."
    )

    phase_summary: Optional[str] = Field(
        None,
        description="A concise summary of findings. Required if action_type is 'finish_phase'."
    )

    @model_validator(mode='after')
    def validate_action(self):
        if self.action_type == "call_tool":
            if not self.tool_name:
                raise ValueError("You selected 'call_tool' but forgot 'tool_name'. Please specify which tool to run.")
            
            # CRITICAL FIX: Enforce patterns for grep_codebase
            if self.tool_name == "grep_codebase":
                if not self.tool_args or not isinstance(self.tool_args, dict):
                    raise ValueError(
                        "You selected 'grep_codebase' but tool_args is missing or invalid. "
                        "You MUST provide: {\"patterns\": [\"keyword1\", \"keyword2\"]}. "
                        "Example: {\"patterns\": [\"docker\", \"s3\", \"lambda\"]}"
                    )
                patterns = self.tool_args.get("patterns")
                if not patterns or not isinstance(patterns, list) or len(patterns) == 0:
                    raise ValueError(
                        "You selected 'grep_codebase' but 'patterns' is missing, empty, or not a list. "
                        "You MUST provide: {\"patterns\": [\"keyword1\", \"keyword2\"]}. "
                        "Example: {\"patterns\": [\"docker\", \"s3\", \"lambda\"]}"
                    )
            
            # Relaxed validation for other tools
            if not self.tool_args:
                self.tool_args = {}

        elif self.action_type == "ask_human":
            if not self.human_question:
                raise ValueError("You selected 'ask_human' but forgot to write the 'human_question'.")

        elif self.action_type == "finish_phase":
            if not self.phase_summary:
                raise ValueError("You selected 'finish_phase' but forgot the 'phase_summary'. Please summarize your findings.")

        return self
