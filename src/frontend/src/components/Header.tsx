import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { HomeIcon } from "@/components/icons";
import type { HeaderData } from "@/types";
import { Fragment, type ReactNode } from "react";

function NavTab({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <a
      href={href}
      className={
        active
          ? "flex h-full items-center border-b-2 border-primary text-sm font-semibold text-foreground"
          : "flex h-full items-center border-b-2 border-transparent text-sm font-medium text-muted-foreground"
      }
    >
      {children}
    </a>
  );
}

export function Header({ data }: { data: HeaderData }) {
  const { nav, breadcrumbs } = data;

  return (
    <>
      <header className="flex h-14 items-center justify-between border-b border-border bg-card px-4 sm:h-16 sm:px-8">
        <nav className="flex h-full items-center gap-4.5 sm:gap-6">
          <NavTab href={nav.notes_url} active={nav.active === "notes"}>
            Заметки
          </NavTab>
          <NavTab href={nav.documents_url} active={nav.active === "documents"}>
            Документы
          </NavTab>
        </nav>

        <div className="flex items-center gap-2 sm:gap-2.5">
          {nav.is_authenticated && (
            <>
              <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
                <a href={nav.add_note_url}>Добавить заметку</a>
              </Button>
              <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
                <a href={nav.add_document_url}>Добавить документ</a>
              </Button>
              <span className="hidden text-[13px] font-medium text-[#3f3f46] sm:inline">{nav.display_name}</span>
              <Avatar className="h-[30px] w-[30px] sm:h-8 sm:w-8">
                <AvatarFallback className="text-[12px] sm:text-[13px]">{nav.initial}</AvatarFallback>
              </Avatar>
            </>
          )}
          {!nav.is_authenticated && (
            <Button asChild variant="ghost" size="sm">
              <a href={nav.login_url}>Войти</a>
            </Button>
          )}
        </div>
      </header>

      <div className="h-10 overflow-x-auto border-b border-[#f0f0f1] bg-card sm:h-11 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <Breadcrumb>
          <BreadcrumbList className="h-10 flex-nowrap whitespace-nowrap px-4 sm:h-11 sm:px-8">
            <BreadcrumbItem>
              {breadcrumbs[0]?.url ? (
                <BreadcrumbLink href={breadcrumbs[0].url}>
                  <HomeIcon size={14} className="text-muted-foreground sm:size-[15px]" />
                </BreadcrumbLink>
              ) : (
                <span className="flex text-muted-foreground">
                  <HomeIcon size={14} className="sm:size-[15px]" />
                </span>
              )}
            </BreadcrumbItem>
            {breadcrumbs.slice(1).map((crumb, i) => (
              <Fragment key={i}>
                <BreadcrumbSeparator />
                <BreadcrumbItem>
                  {crumb.url ? (
                    <BreadcrumbLink href={crumb.url} className="text-xs sm:text-[13px]">
                      {crumb.label}
                    </BreadcrumbLink>
                  ) : (
                    <BreadcrumbPage className="text-xs sm:text-[13px]">{crumb.label}</BreadcrumbPage>
                  )}
                </BreadcrumbItem>
              </Fragment>
            ))}
          </BreadcrumbList>
        </Breadcrumb>
      </div>
    </>
  );
}
