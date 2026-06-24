import streamlit as st
import subprocess
import pty
import os
import threading
import queue
import time
import re

st.set_page_config(page_title="Rcloud Live Terminal", layout="wide")

st.title("📟 Rcloud Agent Terminal Emulator")
st.markdown("Optimized for long-running model inference and tool executions.")
st.markdown("---")

# Global regex to strip terminal color codes
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# --- PERSISTENT BACKGROUND PROCESS MONITOR ---
class ProcessManager:
    def __init__(self):
        self.cmd_queue = queue.Queue()
        self.output_buffer = ""
        self.lock = threading.Lock()
        self.is_working = False  # Track if agent is actively computing
        
        # Open a pseudo-terminal to force unbuffered line generation
        masters, slaves = pty.openpty()
        
        self.proc = subprocess.Popen(
            ["rcloud", "agent", "dev"],
            stdin=subprocess.PIPE,
            stdout=slaves,
            stderr=slaves,
            text=True,
            bufsize=1,
            close_fds=True
        )
        os.close(slaves)
        self.master_fd = os.fdopen(masters, 'r')
        
        # Spin up concurrent read/write workers
        threading.Thread(target=self._stream_reader, daemon=True).start()
        threading.Thread(target=self._stream_writer, daemon=True).start()

    def _stream_reader(self):
        while True:
            try:
                chunk = os.read(self.master_fd.fileno(), 4096)
                if not chunk:
                    break
                
                text_chunk = chunk.decode(errors='ignore')
                clean_chunk = ANSI_ESCAPE.sub('', text_chunk)
                
                with self.lock:
                    self.output_buffer += clean_chunk
                    # If we see the interactive prompt "You:" reappear after Agent finishes speaking,
                    # it means the agent is officially done with the query!
                    if "You:" in clean_chunk and self.is_working and not clean_chunk.strip().startswith("You:"):
                        self.is_working = False
            except Exception:
                break

    def _stream_writer(self):
        while True:
            cmd = self.cmd_queue.get()
            if cmd is None:
                break
            try:
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
            except Exception:
                break
            self.cmd_queue.task_done()

    def get_logs(self):
        with self.lock:
            return self.output_buffer

    def append_to_buffer(self, text):
        with self.lock:
            self.output_buffer += text

    def clear_buffer(self):
        with self.lock:
            self.output_buffer = ""
            
    def is_alive(self):
        return self.proc.poll() is None

@st.cache_resource
def get_manager():
    return ProcessManager()

manager = get_manager()

# --- UI WORKSPACE ---
col1, col2 = st.columns([9, 2])

with col1:
    st.write("**Active Console Stream**")
    terminal_placeholder = st.empty()

with col2:
    st.subheader("Controls")
    if st.button("🧹 Clear Stream"):
        manager.clear_buffer()
        st.rerun()
    if st.button("🔄 Restart Process"):
        st.cache_resource.clear()
        st.rerun()

# --- INPUT HANDLING ---
user_prompt = st.chat_input("Ask about connections, error logs, or metrics...", disabled=manager.is_working)

if user_prompt:
    manager.is_working = True
    manager.append_to_buffer(f"\ You: {user_prompt}\n")
    manager.cmd_queue.put(user_prompt)
    st.rerun()

# --- STREAM RENDERING LOOP ---
# This loop runs continuously as long as the background thread sets manager.is_working to True
if manager.is_working:
    with st.spinner("Agent is running tools and generating response..."):
        while manager.is_working:
            if not manager.is_alive():
                manager.is_working = False
                break
            
            terminal_placeholder.code(manager.get_logs(), language="bash")
            time.sleep(0.15)  # Quick UI refresh frame rate
            
    st.rerun()
else:
    # Standard idle state render
    terminal_placeholder.code(manager.get_logs(), language="bash")