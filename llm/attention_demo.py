#I13/llm/attention_demo.py

import torch
import matplotlib.pyplot as plt

from dataset import CircuitDataset, load_spice_dataset
from transformer import AnalogGPT

SEQ_LEN = 32

text = load_spice_dataset("masala-chai-dataset-new/spice", max_files=200)

dataset = CircuitDataset(text, SEQ_LEN)

model = AnalogGPT(dataset.vocab_size, SEQ_LEN)

model.load_state_dict(torch.load("transformer_circuit.pt"))

model.eval()

sample = text[:SEQ_LEN]

sample_tokens = sample.split()[:SEQ_LEN]
tokens = torch.tensor([[dataset.stoi[t] for t in sample_tokens]])

_ = model(tokens)

attention = model.get_last_attention(layer=0)

attention = attention[0][0].cpu()

plt.figure(figsize=(6,6))
plt.imshow(attention, cmap="viridis")
plt.colorbar()

plt.title("Transformer Attention Map")

plt.xlabel("Token Position")
plt.ylabel("Token Position")

plt.show()