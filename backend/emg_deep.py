from __future__ import annotations

import copy
from typing import Any, Callable

try:
    import torch
    from torch import nn
except ImportError:  # Optional dependency: the catalog reports this honestly.
    torch = None
    nn = None


def torch_status() -> dict[str, Any]:
    return {"available": torch is not None, "device": "cuda" if torch is not None and torch.cuda.is_available() else "cpu", "reason": None if torch is not None else "PyTorch is not installed in the backend environment"}


if nn is not None:
    class MlpClassifier(nn.Module):
        def __init__(self, inputs: int, classes: int, hidden=(64, 32), dropout: float = 0.2):
            super().__init__(); self.network=nn.Sequential(nn.Linear(inputs,hidden[0]),nn.ReLU(),nn.Dropout(dropout),nn.Linear(hidden[0],hidden[1]),nn.ReLU(),nn.Linear(hidden[1],classes))
        def forward(self,x): return self.network(x)

    class Cnn1dClassifier(nn.Module):
        def __init__(self, channels: int, classes: int):
            super().__init__(); self.features=nn.Sequential(nn.Conv1d(channels,16,5,padding=2),nn.ReLU(),nn.BatchNorm1d(16),nn.Conv1d(16,24,3,padding=1),nn.ReLU(),nn.AdaptiveAvgPool1d(1));self.head=nn.Linear(24,classes)
        def forward(self,x): return self.head(self.features(x).squeeze(-1))

    class _TemporalBlock(nn.Module):
        def __init__(self, inputs, outputs, dilation): super().__init__();self.block=nn.Sequential(nn.Conv1d(inputs,outputs,3,padding=dilation,dilation=dilation),nn.ReLU(),nn.Conv1d(outputs,outputs,3,padding=dilation,dilation=dilation),nn.ReLU());self.skip=nn.Conv1d(inputs,outputs,1) if inputs!=outputs else nn.Identity()
        def forward(self,x): return self.block(x)+self.skip(x)

    class TcnClassifier(nn.Module):
        def __init__(self, channels: int, classes: int): super().__init__();self.features=nn.Sequential(_TemporalBlock(channels,16,1),_TemporalBlock(16,24,2),nn.AdaptiveAvgPool1d(1));self.head=nn.Linear(24,classes)
        def forward(self,x): return self.head(self.features(x).squeeze(-1))

    class GruClassifier(nn.Module):
        def __init__(self, channels: int, classes: int, hidden: int = 32): super().__init__();self.gru=nn.GRU(channels,hidden,batch_first=True);self.head=nn.Linear(hidden,classes)
        def forward(self,x): output,_=self.gru(x.transpose(1,2));return self.head(output[:,-1])

    class CnnGruClassifier(nn.Module):
        def __init__(self, channels: int, classes: int): super().__init__();self.conv=nn.Sequential(nn.Conv1d(channels,16,5,padding=2),nn.ReLU());self.gru=nn.GRU(16,32,batch_first=True);self.head=nn.Linear(32,classes)
        def forward(self,x): encoded=self.conv(x).transpose(1,2);output,_=self.gru(encoded);return self.head(output[:,-1])
else:
    MlpClassifier = Cnn1dClassifier = TcnClassifier = GruClassifier = CnnGruClassifier = None


def build_classifier(architecture: str, channels: int, samples: int, classes: int):
    if nn is None:
        raise RuntimeError("PyTorch is not installed")
    if architecture == "MLP": return MlpClassifier(channels * samples, classes)
    if architecture == "CNN_1D": return Cnn1dClassifier(channels, classes)
    if architecture == "TCN": return TcnClassifier(channels, classes)
    if architecture == "GRU": return GruClassifier(channels, classes)
    if architecture == "CNN_GRU": return CnnGruClassifier(channels, classes)
    raise ValueError(f"Unsupported PyTorch architecture: {architecture}")


def _forward(model, architecture: str, values):
    return model(values.flatten(1)) if architecture == "MLP" else model(values)


def train_classifier(
    architecture: str,
    train_x,
    train_y,
    validation_x,
    validation_y,
    *,
    epochs: int,
    seed: int,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if torch is None:
        raise RuntimeError("PyTorch is not installed")
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, min(2, torch.get_num_threads())))
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_x=torch.as_tensor(train_x,dtype=torch.float32,device=device);train_y=torch.as_tensor(train_y,dtype=torch.long,device=device)
    validation_x=torch.as_tensor(validation_x,dtype=torch.float32,device=device);validation_y=torch.as_tensor(validation_y,dtype=torch.long,device=device)
    model=build_classifier(architecture,train_x.shape[1],train_x.shape[2],int(train_y.max().item())+1).to(device)
    optimizer=torch.optim.Adam(model.parameters(),lr=0.01,weight_decay=1e-4);criterion=nn.CrossEntropyLoss();history=[];best_loss=float("inf");best_state=None;best_epoch=0;stale=0
    for epoch in range(1,epochs+1):
        if cancel and cancel(): raise InterruptedError("Training cancelled")
        model.train();optimizer.zero_grad(set_to_none=True);training_loss=criterion(_forward(model,architecture,train_x),train_y);training_loss.backward();optimizer.step()
        model.eval()
        with torch.no_grad(): validation_loss=criterion(_forward(model,architecture,validation_x),validation_y)
        current=float(validation_loss.item());history.append({"epoch":epoch,"training_loss":float(training_loss.item()),"validation_loss":current})
        if current < best_loss-1e-5: best_loss=current;best_state=copy.deepcopy(model.state_dict());best_epoch=epoch;stale=0
        else: stale+=1
        if stale>=8: break
    if best_state is not None:model.load_state_dict(best_state)
    return {"model":model.to("cpu"),"history":history,"best_epoch":best_epoch,"device":str(device),"early_stopped":len(history)<epochs}


def predict_classifier(model, architecture: str, values):
    if torch is None: raise RuntimeError("PyTorch is not installed")
    model.eval()
    with torch.no_grad():return _forward(model,architecture,torch.as_tensor(values,dtype=torch.float32)).argmax(dim=1).cpu().numpy()


def save_classifier(path, model, *, architecture: str, channels: int, samples: int, classes: list[str]) -> None:
    if torch is None: raise RuntimeError("PyTorch is not installed")
    torch.save({"architecture":architecture,"channels":channels,"samples":samples,"classes":classes,"state_dict":model.state_dict()},path)


def load_classifier(path):
    if torch is None: raise RuntimeError("PyTorch is not installed")
    payload=torch.load(path,map_location="cpu",weights_only=True);model=build_classifier(payload["architecture"],payload["channels"],payload["samples"],len(payload["classes"]));model.load_state_dict(payload["state_dict"]);model.eval();return model,payload
