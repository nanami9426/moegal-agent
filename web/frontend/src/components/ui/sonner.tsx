import { Toaster as Sonner, type ToasterProps } from "sonner";

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group"
      closeButton
      position="top-right"
      toastOptions={{
        closeButton: true,
        closeButtonAriaLabel: "关闭通知",
        classNames: {
          toast:
            "group toast group-[.toaster]:rounded-md group-[.toaster]:border group-[.toaster]:bg-card group-[.toaster]:pr-10 group-[.toaster]:text-card-foreground group-[.toaster]:shadow-lg",
          warning: "moegal-toast-warning",
          error: "moegal-toast-error",
          info: "moegal-toast-info",
          description: "group-[.toast]:text-muted-foreground",
          closeButton: "moegal-toast-close",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
