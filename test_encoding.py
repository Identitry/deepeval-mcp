"""Test script to reproduce the unicode encoding error."""

import os
import sys

# Set encoding
print(f"Python version: {sys.version}")
print(f"stdout encoding: {sys.stdout.encoding}")
print(f"Default encoding: {sys.getdefaultencoding()}")
print(f"PYTHONIOENCODING: {os.environ.get('PYTHONIOENCODING', 'not set')}")
print(f"LANG: {os.environ.get('LANG', 'not set')}")
print(f"LC_ALL: {os.environ.get('LC_ALL', 'not set')}")
print()

# Debug API key
api_key = os.environ.get('OPENAI_API_KEY', '')
print(f"API Key length: {len(api_key)}")
print(f"API Key first 10 chars: {api_key[:10] if api_key else 'NOT SET'}")
print(f"API Key last 10 chars: {api_key[-10:] if api_key else 'NOT SET'}")
print(f"API Key has newlines: {repr(api_key.count(chr(10)))}")
print(f"API Key has carriage returns: {repr(api_key.count(chr(13)))}")
print(f"API Key stripped length: {len(api_key.strip())}")
print()

# Test DeepEval import
try:
    import deepeval
    print(f"DeepEval version: {deepeval.__version__}")
except Exception as e:
    print(f"Failed to import deepeval: {e}")
    sys.exit(1)

# Test simple evaluation
from deepeval.metrics import AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase

print("\nCreating test case...")
test_case = LLMTestCase(
    input="What is the capital of France?",
    actual_output="Paris is the capital of France.",
)

print("Creating metric...")
# Check what OpenAI client will use
try:
    from openai import OpenAI
    client = OpenAI()
    print(f"OpenAI client API key length: {len(client.api_key) if client.api_key else 0}")
    print(f"OpenAI client API key first 20: {client.api_key[:20] if client.api_key else 'NOT SET'}")
except Exception as e:
    print(f"Error checking OpenAI client: {e}")

metric = AnswerRelevancyMetric(
    threshold=0.7,
    verbose_mode=False,
    include_reason=True,
)

print("Running evaluation...")
try:
    metric.measure(test_case)
    print(f"Success! Score: {metric.score}")
    print(f"Reason: {metric.reason}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
