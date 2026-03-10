#I13/llm/generate.py

import torch
from transformer import AnalogGPT
from dataset import CircuitDataset, load_spice_dataset

SEQ_LEN = 32

text = load_spice_dataset("masala-chai-dataset-new/spice", max_files=200)

dataset = CircuitDataset(text,SEQ_LEN)

model = AnalogGPT(dataset.vocab_size,SEQ_LEN)

model.load_state_dict(torch.load("transformer_circuit.pt"))

model.eval()

# prompt tokenization

prompt = ".subckt inverter in out vdd vss\n"

prompt_tokens = prompt.split()

context = torch.tensor([[dataset.stoi.get(tok,0) for tok in prompt_tokens]])


for _ in range(400):

    logits = model(context)

    temperature = 0.8

    probs = torch.softmax(logits[:,-1] / temperature, dim=-1)   

    next_token = torch.multinomial(probs,1)

    context = torch.cat([context,next_token],dim=1)

    token_word = dataset.itos[int(next_token)]

    print(token_word , end=" ", flush=True)

print("Generated:\n")

print(" ".join(dataset.itos[int(i)] for i in context[0]))
