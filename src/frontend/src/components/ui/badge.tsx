import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
  {
    variants: {
      variant: {
        // The kind pill on note cards ("Заметка" / "Гарантия" / ...).
        secondary: "bg-secondary text-secondary-foreground",
        // The "N дн." expiry countdown - amber is a semantic urgency color
        // in the mockup, not part of the neutral/indigo theme.
        amber: "bg-[#fffbeb] text-[#b45309] font-semibold",
      },
    },
    defaultVariants: {
      variant: "secondary",
    },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
