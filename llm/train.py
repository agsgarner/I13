#I13/llm/train.py

import torch
from torch.utils.data import DataLoader
from dataset import CircuitDataset, load_spice_dataset
from transformer import AnalogGPT
from tqdm import tqdm

SEQ_LEN = 48
BATCH_SIZE = 8
EPOCHS = 6
LR = 3e-4

device = "mps" if torch.backends.mps.is_available() else "cpu"

print("Using device:", device)

# Load dataset
text = load_spice_dataset("masala-chai-dataset-new/spice", max_files=200)

dataset = CircuitDataset(text, SEQ_LEN)

loader = DataLoader(dataset,
                    batch_size=BATCH_SIZE,
                    shuffle=True)

model = AnalogGPT(dataset.vocab_size, SEQ_LEN, embed_dim=128,layers=3, heads=4).to(device)

optimizer = torch.optim.AdamW(model.parameters(), lr=LR)

loss_fn = torch.nn.CrossEntropyLoss()

for epoch in range(EPOCHS):

    total_loss = 0

    for x,y in tqdm(loader):

        x = x.to(device)
        y = y.to(device)

        logits = model(x)

        loss = loss_fn(
            logits.view(-1, dataset.vocab_size),
            y.view(-1)
        )

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss += loss.item()

    print("Epoch",epoch,"Loss:", total_loss/len(loader))

torch.save(model.state_dict(),"transformer_circuit.pt")