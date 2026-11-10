"""Trace Initialize and pause the recovery probe after its native check."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform77"))
from stage4_launcher77 import Harness77Adapter, main


class RecoveryAdapter(Harness77Adapter):
    def commands(self, parameters, requested):
        self.hold = parameters.get("probe_hold") is True
        return super().commands(parameters, requested)

    def client(self, text):
        call = "result = v.Initialize("
        step = '    CallMarker command, "finished"'
        if text.count(call) != 1 or text.count(step) != 1:
            raise ValueError("the stage-4 client is missing the recovery probe checkpoints")
        text = text.replace(call, 'Emit "probe57", "Initialize", "invoke", 0\n' + call)
        if self.hold:
            text = text.replace(step, step + """
    If command = "check" Then
        Dim releasePath, heldSince
        releasePath = fso.BuildPath(fso.GetParentFolderName(eventPath), "probe-release")
        CallMarker "probe", "holding"
        heldSince = CDbl(Timer)
        Do While Not fso.FileExists(releasePath)
            If Elapsed(heldSince) > 240000 Then Fail "recovery-probe", "release missing"
            WScript.Sleep 25
        Loop
    End If
""")
        return text


if __name__ == "__main__":
    raise SystemExit(main(adapter=RecoveryAdapter()))
