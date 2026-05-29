import os
import logging
from llama_cpp import Llama

logger = logging.getLogger(__name__)

class DirectLLM:
    def __init__(self):
        # Path to your model
        model_path = os.getenv("MODEL_PATH", "models/qwen3.5-0.8b")
        
        # Ensure path is absolute if relative
        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found at: {model_path}")

        logger.info(f"⏳ Loading model: {model_path} ...")
        
        # Initialize Llama
        # n_ctx: Context window (2B model handles 4k easily)
        # n_threads: Use all available CPU cores (optional, defaults to auto)
        # verbose: False to keep logs clean
        self.llm = Llama(
            model_path=model_path,
            n_ctx=16096,
            n_threads=6, 
            n_gpu_layers=0, # Set >0 if you have NVIDIA GPU + cuBLAS build
            verbose=False
        )
        logger.info("✅ Model loaded directly into memory!")

    def generate(self, prompt, max_tokens=1024, temperature=0.7, stop_tokens=None):
        """Generate text directly."""
        try:
            output = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop_tokens,
                echo=False
            )
            return output['choices'][0]['text']
        except Exception as e:
            logger.error(f"Inference error: {e}")
            raise

# Global Instance
_llm_instance = None

def init_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = DirectLLM()
    return _llm_instance

def get_llm():
    if _llm_instance is None:
        return init_llm()
    return _llm_instance
