# At the absolute top - NO IMPORTS BEFORE THIS
from dotenv import load_dotenv
load_dotenv()

from app import invoke_agent

def main():
    print("vm-health_monitor local dev is ready. Type 'exit' to quit.\n")
    # State tracking setup
    history = []
    
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
            
        if not user_input:
            continue
            
        if user_input.lower() in {"exit", "quit"}:
            print("Bye.")
            break
            
        try:
            # We pass the history list to invoke_agent, and expect a tuple back
            output, history = invoke_agent(user_input, history)
            print(f"Agent: {output}\n")
        except Exception as exc:
            print(f"Error: {exc}\n")

if __name__ == "__main__":
    main()