"""
example of how to create a new assistant using all the parameters for the assistant creation API
https://platform.openai.com/docs/api-reference/assistants/createAssistant
"""

import json
import os
import time
from openai import OpenAI

create_tool_function = """
def create_tool(tool_name=None, tool_description=None, tool_parameters=None, tool_code=None, required_action_by_user=None):
    \"\"\"
    returns a tool that can be used by other assistants
    \"\"\"

    # create the tool file
    os.makedirs('tools', exist_ok=True)
    with open(f'tools/{tool_name}.py', 'w') as f:
        f.write(tool_code)
    
    # create the tool details file
    tool_details = {
        'name': tool_name,
        'description': tool_description,
        'parameters': tool_parameters,
    }

    with open(f'tools/{tool_name}.json', 'w') as f:
        json.dump(tool_details, f, indent=4)

    return_value = f'created tool at tools/{tool_name}.py with details tools/{tool_name}.json\\n\\n'
    return_value += f'There is a required action by the user before the tool can be used: {required_action_by_user}'

    return return_value
"""

# these files will be uploaded to the platform and used by the assistant
files_for_assistant = []

instructions_for_assistant = "You create tools to accomplish arbitrary tasks. Write and run code to implement the interface for these tools using the OpenAI API format. You do not have access to the tools you create. Instruct the user that to use the tool, they will have to create an assistant equipped with that tool, or consult with the AssistantCreationAssistant about the use of that tool in a new assistant."

example_tool = """
def new_tool_name(param1=None, param2='default_value'):
    if not param1: 
        return None

    # does something with the parameters to get the result
    intermediate_output = ...

    # get the tool output
    tool_output = ...

    return tool_output
"""

assistant_details = {
    'build_params' : {
        'model': "gpt-4-1106-preview", 
        'name': "Tool Creator",
        'description': "Assistant to create tools for use in the OpenAI platform by other Assistants. ",
        'instructions': instructions_for_assistant, 
        'tools': [
            {
                "type": "function", 
                "function": {
                    "name": "create_tool",
                    "description": "returns a tool that can be used by other assistants. specify the tool_name, tool_description, tool_parameters, and tool_code. all of those are required. use the JSON schema for all tool_parameters.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool_name": {
                                "type": "string",
                                "description": "The name of the tool, using snake_case e.g. new_tool_name",
                            },
                            "tool_description": {
                                "type": "string",
                                "description": "The description of the tool, e.g. This tool does a computation using param1 and param2 to return a result that ...",
                            },
                            "tool_parameters": {
                                "type": "string",
                                "description": 'The parameters of the tool, using JSON schema to specify the type and properties for each parameter.\n\ne.g.\n\n{"type": "object", "properties": {"location": {"type": "string", "description": "The city and state e.g. San Francisco, CA"}, "unit": {"type": "string", "enum": ["c", "f"]}}, "required": ["location"]}',
                            },
                            "tool_code": {
                                "type": "string",
                                "description": f"The code for the tool, e.g. \n{example_tool}",
                            },
                            "required_action_by_user": {
                                "type": "string",
                                "description": "Optional. The action required by the user before the tool can be used, e.g. 'set up API keys for service X and add them as environment variables'. It's important to be as detailed as possible so that these tools can be used for arbitrary tasks. If there is nothing required, do not include this parameter.",
                            },
                        },
                        "required": ["tool_name", "tool_description", "tool_parameters", "tool_code"],
                    },
                }
            },
        ],
        'file_ids': [],
        'metadata': {},
    },
    'file_paths': files_for_assistant,
    'functions': {
        'create_tool': create_tool_function,
    },  
}

client = OpenAI() # be sure to set your OPENAI_API_KEY environment variable


# check if tool_creator.json exists
os.makedirs('assistants', exist_ok=True)
if os.path.exists('assistants/tool_creator.json'):
    with open('assistants/tool_creator.json') as f:
        assistant_from_json = json.load(f)
    
    tool_creator = client.beta.assistants.retrieve(assistant_from_json['assistant_id'])
    print(f"Loaded assistant details from tool_creator.json\n\n" + 90*"-" + "\n\n", flush=True)

    assistant_details = assistant_from_json['assistant_details']

else:
    # create the assistant
    tool_creator = client.beta.assistants.create(**assistant_details["build_params"])

    # created assistant
    print(f"Created assistant: {tool_creator.id}\n\n" + 90*"-" + "\n\n", flush=True)

    # save the assistant info to a json file
    info_to_export = {
        "assistant_id": tool_creator.id,
        "assistant_details": assistant_details,
    }
    with open('assistants/tool_creator.json', 'w') as f:
        json.dump(info_to_export, f, indent=4)

# load the functions into the execution environment
for func in assistant_details['functions']:
    # define the function in this execution environment
    exec(assistant_details['functions'][func], globals())
 
    # add the function to the assistant details
    assistant_details['functions'][func] = eval(func)

# Create thread
thread = client.beta.threads.create()

while True:
    user_message = input("You: ")

    # add user message to thread
    thread_message = client.beta.threads.messages.create(
      thread.id,
      role="user",
      content=user_message,
    ) 

    # get assistant response in thread
    run = client.beta.threads.runs.create(
      thread_id=thread.id,
      assistant_id=tool_creator.id,
    )

    # wait for run to complete
    wait_time = 0
    while True:
        if wait_time % 5 == 0:
            print(f"waiting for run to complete...", flush=True)
        wait_time += 1
        time.sleep(1)

        run = client.beta.threads.runs.retrieve(
          thread_id=thread.id,
          run_id=run.id,
        )

        if run.status == "completed":
            break
        elif run.status == "in_progress":
            continue
        elif run.status == "requires_action":
            if run.required_action.type == 'submit_tool_outputs':
                tool_calls = run.required_action.submit_tool_outputs.tool_calls

                tool_outputs = []
                for tc in tool_calls:
                    function_to_call = eval(tc.function.name)
                    function_args = json.loads(tc.function.arguments)
                    function_response = function_to_call(**function_args)

                    tool_outputs.append({
                        "tool_call_id": tc.id,
                        "output": function_response,
                    })

                print(f"Submitting tool outputs...", flush=True)
                run = client.beta.threads.runs.submit_tool_outputs(
                  thread_id=thread.id,
                  run_id=run.id,
                  tool_outputs=tool_outputs
                )
        else:
            try:
                input(f'Run status: {run.status}. press enter to continue, or ctrl+c to quit')
            except KeyboardInterrupt:
                exit()                       

    # get most recent message from thread
    thread_messages = client.beta.threads.messages.list(thread.id, limit=10, order='desc')

    # get assistant response from message
    assistant_response = thread_messages.data[0].content[0].text.value

    print(f"\n\nBot: {assistant_response}\n\n", flush=True)

    # continue?
    try:
        input("Press enter to create another tool, or ctrl+c to quit")
    except KeyboardInterrupt:
        break

