#I13/llm/transformer_demo.py

import torch
import matplotlib.pyplot as plt

from dataset import CircuitDataset, load_spice_dataset
from transformer import AnalogGPT

import os
assert os.path.exists("transformer_circuit.pt"), "Checkpoint transformer_circuit.pt not found! Run train.py first."

SEQ_LEN = 48

print("\nLoading dataset...")

text = load_spice_dataset("masala-chai-dataset-new/spice", max_files=200)

dataset = CircuitDataset(text, SEQ_LEN)

print("Dataset tokens:", len(dataset.data))
print("Vocabulary size:", dataset.vocab_size)

print("\nLoading trained model...")

model = AnalogGPT(
    dataset.vocab_size,
    SEQ_LEN,
    embed_dim=128,
    layers=3,
    heads=4
)

model.load_state_dict(torch.load("transformer_circuit.pt"))

model.eval()

params = sum(p.numel() for p in model.parameters())

print("Model parameters:", params)

print("\n=================================")
print("Analog Circuit Generation Demo")
print("=================================\n")

prompt = ".subckt inverter in out vdd vss"

print("Prompt:")
print(prompt)
print("\nGenerating netlist...\n")

tokens = [dataset.stoi.get(tok,0) for tok in prompt.split()]
context = torch.tensor([tokens])

for _ in range(60):

    logits = model(context)

    probs = torch.softmax(logits[:,-1],dim=-1)

    next_token = torch.multinomial(probs,1)

    context = torch.cat([context,next_token],dim=1)

    context = context[:,-SEQ_LEN:]

    word = dataset.itos[int(next_token)]

    print(word,end=" ",flush=True)

print("\n\nGeneration complete.")

print("\nShowing attention visualization...")

# Run forward pass to capture attention
_ = model(context)

attention = model.get_last_attention(layer=0)

attention = attention[0][0].detach().cpu()

plt.figure(figsize=(6,6))

plt.imshow(attention, cmap="viridis")

plt.title("Transformer Attention Map")

plt.xlabel("Token Position")
plt.ylabel("Token Position")

plt.colorbar()

plt.show()