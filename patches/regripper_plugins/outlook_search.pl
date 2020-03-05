#-----------------------------------------------------------
# outlook_search.pl
# Plugin for Registry Ripper
#
# Change history
#   20181005 - created
#
# References
#    https://getadmx.com/?Category=Office2016&Policy=outlk16.Office.Microsoft.Policies.Windows::L_SetDefaultSearchScope
#
# Author: mcardona
#-----------------------------------------------------------
package outlook_search;
use strict;

my %config = (hive          => "NTUSER\.DAT",
              hasShortDescr => 1,
              hasDescr      => 0,
              hasRefs       => 0,
              osmask        => 22,
              version       => 20181005);

sub getConfig{return %config}
sub getShortDescr {
    return "Gets user's Outlook search files";  
}
sub getDescr{}
sub getRefs {}
sub getHive {return $config{hive};}
sub getVersion {return $config{version};}

my $VERSION = getVersion();

sub pluginmain {
    my %search_behaviour;
    $search_behaviour{"0"} = "Default behavior";
    $search_behaviour{"1"} = "All Mailboxes";
    $search_behaviour{"2"} = "Current Mailbox";
    my $class = shift;
    my $ntuser = shift;
    ::logMsg("Launching outlook_search v.".$VERSION);
    ::rptMsg("(".getHive().") ".getShortDescr()."\n"); # banner
    my $reg = Parse::Win32Registry->new($ntuser);
    my $root_key = $reg->get_root_key;

    # checck different versions of Outlook
    my $version;
    my @versions = ("7\.0","8\.0","9\.0","10\.0","11\.0","12\.0","14\.0","15\.0","16\.0");
    foreach my $ver (@versions) {
        my $tag = 0;
        my $key_path = "Software\\Microsoft\\Office\\".$ver."\\Outlook\\Search";
        if (defined($root_key->get_subkey($key_path))) {
            $version = $ver;
            $tag = 1;
        }
    
        if ($tag) {
            ::rptMsg("MSOffice version ".$version." located.");
            my $key_path = "Software\\Microsoft\\Office\\".$version."\\Outlook";
            my $of_key = $root_key->get_subkey($key_path);
            if ($of_key) {
                # Attempt to retrieve Search files
                my @word = ('Search', 'Search\\Catalog');
                foreach my $k (@word) {
                    if (my $word_key = $of_key->get_subkey($k)) {
                        ::rptMsg("\n".$key_path."\\".$k);
                        ::rptMsg("LastWrite Time ".gmtime($word_key->get_timestamp())." (UTC)");
                        my @vals = $word_key->get_list_of_values();
                        if (scalar(@vals) > 0) {
                            my $defSearchScope = "";
                            # Retrieve values
                            foreach my $v (@vals) {
                                my $val = $v->get_name();
                                if ($val eq "DefaultSearchScope"){
                                    $defSearchScope = $v->get_data();
                                }
                                else{
                                    ::rptMsg("  ".$val);
                                }
                            }
                            if ($defSearchScope ne ""){
                                ::rptMsg("\n  Default search scope: ".$search_behaviour{$defSearchScope});
                            }
                        }
                    }
                }
                my $profile = 'Profiles';
                my $of_key = $root_key->get_subkey($key_path);
                if (my $word_key = $of_key->get_subkey($profile)) {
                    ::rptMsg("\n".$key_path."\\".$profile);
                    ::rptMsg("LastWrite Time ".gmtime($word_key->get_timestamp())." (UTC)\n");
                    my @vals = $word_key->get_list_of_subkeys();

                    if (scalar(@vals) > 0) {
                        foreach my $v (@vals) {
                            my $val = $v->get_name();
                            ::rptMsg("  ".$key_path."\\".$profile."\\".$val);
                            ::rptMsg("    LastWrite Time ".gmtime($v->get_timestamp())." (UTC)\n");
                        }
                    }
                }
            }
            else {
                ::rptMsg("Could not access ".$key_path);
                ::logMsg("Could not access ".$key_path);
            }
        }
    }
}

1;
