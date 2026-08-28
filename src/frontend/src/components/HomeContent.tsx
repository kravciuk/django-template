import { FileIcon } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { HomeData, NoteCard } from "@/types";

function NoteCardItem({ note }: { note: NoteCard }) {
  return (
    <Card className="p-3.5 sm:p-4">
      <div className={note.has_cover ? "flex items-start gap-2.5 sm:gap-3" : ""}>
        {note.has_cover && note.cover_url && (
          <img
            src={note.cover_url}
            alt=""
            className="h-14 w-14 shrink-0 rounded-lg object-cover sm:h-16 sm:w-16"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <a href={note.detail_url} className="text-[13px] font-medium text-foreground sm:text-sm">
              {note.title}
            </a>
            <Badge className="shrink-0">{note.kind_label}</Badge>
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground sm:text-xs">{note.created_at_display}</div>
          <div className="mt-1.5 line-clamp-1 text-xs text-[#52525b] sm:text-[13px]">{note.excerpt}</div>
        </div>
      </div>
    </Card>
  );
}

function DocumentsPanel({ documents }: { documents: NonNullable<HomeData["documents"]> }) {
  return (
    <div className="flex flex-col gap-4 lg:col-start-2">
      <Card className="p-3.5 sm:p-4">
        <h3 className="mb-2 text-sm font-semibold text-foreground">Недавно добавленные</h3>
        {documents.recent.length === 0 && (
          <p className="text-xs text-muted-foreground">Пока нет добавленных документов</p>
        )}
        {documents.recent.map((doc, i) => (
          <div
            key={doc.detail_url}
            className={`flex items-center gap-2 py-1.5 sm:py-2${i > 0 ? " border-t border-[#f0f0f1]" : ""}`}
          >
            <FileIcon size={14} className="shrink-0 text-muted-foreground sm:size-[15px]" />
            <a
              href={doc.detail_url}
              className="min-w-0 flex-1 truncate text-xs font-medium text-foreground sm:text-[13px]"
            >
              {doc.title}
            </a>
            <span className="shrink-0 text-[10px] text-muted-foreground sm:text-[11px]">{doc.date_display}</span>
          </div>
        ))}
      </Card>

      <Card className="p-3.5 sm:p-4">
        <h3 className="mb-2 text-sm font-semibold text-foreground">Истекают в течение 30 дней</h3>
        {documents.expiring.length === 0 && (
          <p className="text-xs text-muted-foreground">Ничего не истекает в ближайшие 30 дней</p>
        )}
        {documents.expiring.map((doc, i) => (
          <div
            key={doc.detail_url}
            className={`flex items-center justify-between gap-2 py-2${i > 0 ? " border-t border-[#f0f0f1]" : ""}`}
          >
            <div className="min-w-0">
              <a href={doc.detail_url} className="block truncate text-xs font-medium text-foreground sm:text-[13px]">
                {doc.title}
              </a>
              <div className="mt-0.5 text-[10px] text-muted-foreground sm:text-[11px]">
                до {doc.expires_at_display}
              </div>
            </div>
            <Badge variant="amber" className="shrink-0">
              {doc.days_left} дн.
            </Badge>
          </div>
        ))}
      </Card>
    </div>
  );
}

export function HomeContent({ data }: { data: HomeData }) {
  return (
    <main className="grid grid-cols-1 gap-6 px-4 py-5 sm:px-8 sm:py-7 lg:grid-cols-[4fr_3fr_3fr]">
      <section>
        <h2 className="mb-3 text-[15px] font-semibold text-foreground sm:text-base">Последние заметки</h2>
        <div className="flex flex-col gap-2 sm:gap-2.5">
          {data.notes.length === 0 && (
            <p className="text-sm text-muted-foreground">Пока нет опубликованных заметок.</p>
          )}
          {data.notes.map((note) => (
            <NoteCardItem key={note.public_id} note={note} />
          ))}
        </div>
      </section>

      {data.documents && <DocumentsPanel documents={data.documents} />}

      <div className="min-h-40 rounded-lg border-[1.5px] border-dashed border-[#d4d4d8] lg:col-start-3 lg:min-h-full">
        <div className="flex h-full min-h-40 items-center justify-center">
          <span className="text-[13px] font-medium text-muted-foreground">Зарезервировано</span>
        </div>
      </div>
    </main>
  );
}
