import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function OverviewSkeleton() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ListSkeleton />
      <ListSkeleton />
    </div>
  );
}

export function ListSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton className="h-20 w-full" key={index} />
        ))}
      </CardContent>
    </Card>
  );
}
