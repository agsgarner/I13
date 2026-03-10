#I13/llm/dataset.py

import torch
from torch.utils.data import Dataset

def load_spice_dataset(folder, max_files=200):
    """
    Reads all spice netlist files and concatenates them.
    """

    import os

    text = ""
    count = 0

    for file in sorted(os.listdir(folder)):

        if file.endswith(".txt"):

            path = os.path.join(folder, file)

            with open(path) as f:
                text += f.read() + "\n"
            
            count += 1
    
            if count >= max_files:
                break

    return text

class CircuitDataset(Dataset):
    """
    Dataset for training a language model.

    Converts raw text into integer tokens and returns
    sequences used for next-token prediction.
    """

    def __init__(self, text, seq_len):

        # Build vocabulary (unique characters)
        tokens = text.split()
        vocab = sorted(set(tokens))

        self.stoi = {tok:i for i,tok in enumerate(vocab)}
        self.itos = {i:tok for tok,i in self.stoi.items()}

        self.vocab_size = len(vocab)
        self.seq_len = seq_len

        # Convert entire dataset to integer tokens
        self.data = torch.tensor([self.stoi[t] for t in tokens])

    def __len__(self):
        return len(self.data) - self.seq_len

    def __getitem__(self, idx):

        # Input sequence
        x = self.data[idx:idx+self.seq_len]

        # Target sequence (shifted by 1)
        y = self.data[idx+1:idx+self.seq_len+1]

        return x, y