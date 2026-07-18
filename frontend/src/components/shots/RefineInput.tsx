import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface RefineInputProps {
  onRefine: (instruction: string) => void;
  disabled?: boolean;
  loading?: boolean;
}

export function RefineInput({ onRefine, disabled, loading }: RefineInputProps) {
  const [instruction, setInstruction] = useState("");

  const handleSubmit = () => {
    const trimmed = instruction.trim();
    if (!trimmed) return;
    onRefine(trimmed);
    setInstruction("");
  };

  return (
    <div className="space-y-3">
      <label htmlFor="refine-input" className="text-xs uppercase tracking-wider text-silver">
        Refine in plain language
      </label>
      <Textarea
        id="refine-input"
        placeholder='e.g. "make it high-angle, extremely wide, low-key lighting"'
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        disabled={disabled || loading}
        className="min-h-[100px] font-sans"
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            handleSubmit();
          }
        }}
      />
      <Button
        onClick={handleSubmit}
        disabled={disabled || loading || !instruction.trim()}
        variant="secondary"
        size="sm"
      >
        {loading ? "Refining…" : "Refine shot"}
      </Button>
    </div>
  );
}
