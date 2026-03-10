#I13/llm/transformer.py

import torch
import torch.nn as nn
import torch.nn.functional as F
import math


class SelfAttention(nn.Module):
    """
    Multi-head causal self-attention.

    Stores attention weights for visualization.
    """

    def __init__(self, embed_dim, num_heads, block_size, dropout=0.1):
        super().__init__()

        assert embed_dim % num_heads == 0

        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads

        self.q_proj = nn.Linear(embed_dim, embed_dim)
        self.k_proj = nn.Linear(embed_dim, embed_dim)
        self.v_proj = nn.Linear(embed_dim, embed_dim)

        self.out_proj = nn.Linear(embed_dim, embed_dim)

        self.dropout = nn.Dropout(dropout)

        # causal mask
        self.register_buffer(
            "mask",
            torch.tril(torch.ones(block_size, block_size))
        )

        # store attention weights for demo
        self.last_attention = None

    def forward(self, x):

        B, T, C = x.shape

        q = self.q_proj(x)
        k = self.k_proj(x)
        v = self.v_proj(x)

        q = q.view(B, T, self.num_heads, self.head_dim).transpose(1, 2)
        k = k.view(B, T, self.num_heads, self.head_dim).transpose(1, 2)
        v = v.view(B, T, self.num_heads, self.head_dim).transpose(1, 2)

        scores = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)

        scores = scores.masked_fill(self.mask[:T, :T] == 0, float("-inf"))

        attn = F.softmax(scores, dim=-1)

        attn = self.dropout(attn)

        # store attention weights for visualization
        self.last_attention = attn.detach()

        out = attn @ v

        out = out.transpose(1, 2).contiguous().view(B, T, C)

        return self.out_proj(out)


class TransformerBlock(nn.Module):
    """
    Standard transformer block.
    """

    def __init__(self, embed_dim, num_heads, block_size, dropout=0.1):
        super().__init__()

        self.ln1 = nn.LayerNorm(embed_dim)
        self.ln2 = nn.LayerNorm(embed_dim)

        self.attn = SelfAttention(embed_dim, num_heads, block_size, dropout)

        self.ff = nn.Sequential(
            nn.Linear(embed_dim, 4 * embed_dim),
            nn.GELU(),
            nn.Linear(4 * embed_dim, embed_dim),
            nn.Dropout(dropout)
        )

    def forward(self, x):

        x = x + self.attn(self.ln1(x))
        x = x + self.ff(self.ln2(x))

        return x


class AnalogGPT(nn.Module):
    """
    GPT-style transformer model for circuit netlists.
    """

    def __init__(
        self,
        vocab_size,
        block_size,
        embed_dim=128,
        layers=2,
        heads=2,
        dropout=0.1
    ):
        super().__init__()

        self.block_size = block_size

        self.token_emb = nn.Embedding(vocab_size, embed_dim)
        self.pos_emb = nn.Embedding(block_size, embed_dim)

        self.blocks = nn.ModuleList([
            TransformerBlock(embed_dim, heads, block_size, dropout)
            for _ in range(layers)
        ])

        self.norm = nn.LayerNorm(embed_dim)

        self.head = nn.Linear(embed_dim, vocab_size)

    def forward(self, tokens):

        B, T = tokens.shape

        pos = torch.arange(T, device=tokens.device)

        x = self.token_emb(tokens) + self.pos_emb(pos)

        for block in self.blocks:
            x = block(x)

        x = self.norm(x)

        logits = self.head(x)

        return logits


    @torch.no_grad()
    def generate(self, tokens, max_new_tokens):
        """
        Generate tokens autoregressively.
        """

        for _ in range(max_new_tokens):

            tokens_cond = tokens[:, -self.block_size:]

            logits = self(tokens_cond)

            logits = logits[:, -1, :]

            probs = F.softmax(logits, dim=-1)

            next_token = torch.multinomial(probs, num_samples=1)

            tokens = torch.cat([tokens, next_token], dim=1)

        return tokens


    def get_last_attention(self, layer=0):
        """
        Returns stored attention weights from a transformer layer.
        Used for visualization.
        """

        return self.blocks[layer].attn.last_attention