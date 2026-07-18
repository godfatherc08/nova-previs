import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

interface LockConfirmProps {
  shotId: string;
  version: number;
  onConfirm: () => void;
  disabled?: boolean;
  loading?: boolean;
}

export function LockConfirm({
  shotId,
  version,
  onConfirm,
  disabled,
  loading,
}: LockConfirmProps) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button disabled={disabled || loading} variant="default">
          {loading ? "Locking…" : "Lock this shot"}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Lock shot {shotId}</AlertDialogTitle>
          <AlertDialogDescription>
            Version v{version} will be written to storage with Object Lock and
            trigger animatic generation. This version becomes read-only — refining
            after lock creates a new version, never mutates the locked one.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            Lock v{version}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
